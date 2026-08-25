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

- **Sharded layout** (`manifestPath` is an *index* whose phases are `{id, title, shard}` stubs
  pointing at `phases/<phaseId>.json` — the **stubs** are what decides the layout, and
  `meta.version: 3` is a stamp that follows them, which is why every reader asks
  `_manifest_io.is_sharded()` and not the stamp): every per-phase / per-task
  **runtime** field — phase `status`/`branch`/`baseRef`/`mergedAt`/`review`/`summary`/`claim` and
  task `status`/`attempts`/`startedAt`/`completedAt`/`outcome`/`commit` — lives in that phase's
  **shard**. Edit the SHARD, never the index. **Structural** writes (adding a phase/task/bug,
  `fileIndex`, `bugs[]`, `proposals[]`) go to the **index** under the index lock. A phase run therefore touches
  **only its own shard** — which is exactly why two phase branches merge without a manifest conflict.
- **Single-file layout** (no phase carries a `shard`; `meta.version: 2` or absent): it's all
  one file, as before.
- **Neither layout is legacy, and a mutating command should not nudge.** The two shapes are a
  CHOICE, not an age: a single-file manifest never goes out of date, and installing a newer plugin
  never makes a layout change due. Sharding earns its keep when phases run in parallel from
  separate worktrees, or when the index is large enough that per-phase context cost matters — one
  session with few phases is better off single-file. If asked, say that; do not volunteer it on
  every write. The command is **`/audit:layout <sharded|single-file>`** and it moves in **either**
  direction, so there is no direction to apologise for — the doer underneath is
  `migrate-manifest.py --to=sharded|single-file`, named here as well so this paragraph survives a
  command rename. The reverse has a cost the forward one does not, and `layout.md` is where it is
  stated rather than here. (`/audit:migrate` is the legacy spelling of `/audit:layout sharded`,
  kept for existing transcripts and slated for removal.)

Below, "**Edit the phase's manifest file**" means the shard in the sharded layout, the one file otherwise.

## Preflight

Run the checks relevant to the command. **Read-only commands (`status`, `report`, `doctor`) run only 1–2;
mutating commands (`next`, `run`, `phase`, `review`, `resume`) run all of 1–6 before acting.**

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
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --submodules "<gitRoot>/.gitmodules" --git-root "<gitRoot>"`
   (omit `--git-root` when gitRoot is `.`). Exit 1 means one or more `task.files` live inside a git
   **submodule** — a separate nested repo the parent CANNOT stage/commit (`git add` fails with
   "Pathspec is in submodule"). **STOP** and relay its output: point `meta.gitRoot` at that submodule
   (to audit it directly), or remove those files from the task(s). Do not start a run that will fail
   at commit time.
5. **Acquire the lock** (mutating commands) — see **Concurrency lock**.
6. **Budget check** (`next`, `run`, `phase` — after the lock, so an ask keeps it). Only when
   the target phase declares `budgetUSD` AND metering has recorded something; otherwise skip
   silently. Read it, never recompute it:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --json` carries
   `usage.budgets.phases[]` with `spent`, `budget`, `pct` and `over` already resolved.
   - **`pct` under 80** — say nothing. A phase inside its budget is not news.
   - **`pct` 80–99** — one line, once per phase per session:
     `[BUDGET] <id> at <pct>% (<spent> of <budget>) — <n> task(s) still to run.` Then continue.
     Do NOT repeat it on every task: a warning that reappears each turn is a warning nobody
     reads (the same reason `meter-usage.py` de-dups its advisory per task).
   - **`pct` at or over 100** — **AskUserQuestion before spawning the next executor**, with the
     phase, the overrun and the remaining task count stated: (a) **continue** — the budget was an
     estimate; (b) **stop here** — leave the phase `in_progress` and resume later; (c) **raise
     `budgetUSD`** to a number the human gives, then continue. Never pick for them, and never
     raise it yourself.

   This is a gate on *starting* work, not on finishing it. A task already mid-edit is never
   interrupted for spend — stopping there strands a half-finished change, which is the same
   reasoning that keeps `meter-usage.py` advisory. And it never fires when `usage.showCost` is
   false: naming dollars would leak exactly what that setting exists to hide.

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
- `meta.reviewSkill` — DEFAULT skill invoked at phase sign-off (default **null** → skip; tests are the signer).
  A phase can override it, and a registered area sits between the two — see `meta.areas` below.
- `meta.areas` — OPTIONAL registry of the areas a phase's `area` tag can name:
  `{tag: {root, description, reviewSkill?, skills?, owner?}}`. Registration is optional in both directions —
  a tag with no entry stays legal (the validator warns; nothing refuses), an entry no phase uses is
  legal too — so a single-app repo writes nothing and behaves exactly as before. `root` is relative
  to the PROJECT dir, like `task.files`. Registering a tag gives it two resolutions, and **both are
  stated identically wherever they are used** (here, in Phase sign-off step 1, in the executor spawn,
  in `review.md` and in `manifest-conventions.md`):
  - **Review skill** — `phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`. The
    first level that is **present** answers, and an explicit `null` **is** an answer (skip review;
    tests are the signer) — it does not fall through.
  - **Executor skills** — each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped,
    **area first** (house conventions before task specifics).
  - When a phase carries **several tags**, WRITTEN ORDER decides: the first tag whose area declares
    the field answers. `/audit:status` prints the resolved reviewer and the basis it came from
    (`review: backend-review (area api)`), so you never have to re-derive this by hand.
  - An area may also declare an advisory **`owner`** (v0.34) — who to coordinate with, never an
    assignee; nothing gates on it. If the plan gate's heads-up names an owner mismatch during a
    task, carry it into the handoff — coordination is the point, the edit itself is fine.
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
- **Branch operations pre-approved:** `git switch -c <glob>`, `git switch <glob>`,
  `git merge --ff-only <glob>`, `git branch -d <glob>` for every glob
  `resolve-branch.py <manifestPath> --globs` prints. All other branch/checkout ops need confirmation.
  **Derive the globs, do not assume them** — a manifest using `meta.branch` has one per type
  (`feature/*`, `bugfix/*`, …) while a `meta.branchPrefix` manifest has exactly one. Guessing
  costs a confirmation prompt on every branch operation, which reads as a harness fault rather
  than a config one.
- **Never read secrets** and **never log tokens** — enforced by the plugin's guard hooks; do not work around them.
- If `meta.nodePreamble` is set, run it (un-piped) before any build/lint/test command.
- Every manifest write goes through `Edit` and must keep the JSON valid — after each mutation run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` and fix any findings
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

**`phase.priority` re-sorts that order, and nothing else.** An optional positive integer on a
phase says which of the **already ready** tasks to reach for first: tier 1 (unique) leads, then
higher tiers, then every phase with no priority at all — which keeps its written position among
its peers, so a plan carrying no `priority` runs exactly as this rule describes. It never makes an
unready task ready and never skips a dependency: a pinned phase whose `blockedBy` is unsatisfied
is **skipped**, and `/audit:status` prints the note that says so and names the task running
instead. Read it, never repair it — a pinned phase that depends on unfinished work is a
contradiction to REPORT (`/audit:phase priority` is what changes it). In the sharded layout the
field lives on the **index stub** only; a copy in a shard body is ignored, and the validator says
it was.

**Parallel safety:** tasks whose `files` sets are disjoint AND whose `dependsOn` lists are mutually satisfied may
run in parallel (spawn multiple Agents in one message). Tasks sharing a file or linked via `dependsOn` run sequentially.

## Concurrency lock

Locks live in the **shared git directory**, not the working tree — so they coordinate across git
**worktrees/clones on one machine** AND never appear as a working-tree change (no `git status` /
hook noise).

**Do not hand-roll the lock. Run the script and read its exit code:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" acquire <name> \
        --project <gitRoot> --note "<verb> <scope>"
```

`<name>` is one of the **two tiers — take the narrowest lock that covers your writes:**

- **`index`** — held **briefly** for STRUCTURAL writes and id allocation: `init`, `task`, `bug`,
  `sync`, allocating a new phase/task/bug id, and the phase **status-mirror** write in the index.
  Acquire → edit the index → release, within that step.
- **`phase-<phaseId>`** — held for the DURATION of a phase run by `next`/`run`/`phase`/`review`/
  `resume` on that phase. Two DIFFERENT phases take two different locks → they run in **parallel**
  (separate worktrees), each writing only its own shard. A run that must also allocate an id or
  touch the index takes the index lock too, briefly (nested), then releases it.

**Exit codes are the protocol:**

| Exit | Meaning | What you do |
|---|---|---|
| **0** | acquired | proceed |
| **3** | held by a **live** run | **STOP.** Print the script's output verbatim and end the command. Do not take it over. |
| **4** | holder is **not alive** | Print the output, ask the human (AskUserQuestion) to confirm, then rerun with `--takeover`. |
| **1** | not a git repo / cannot write | Stop and report. Fall back to `<manifestPath>.lock` only if you have no git repo at all — that path coordinates within a single clone only. |

**Exit 3 is enforced, not just advised (0.27.0).** `require-plan.py` refuses a write to the
manifest or a phase shard while another LIVE session holds the governing lock, so ignoring a
refusal here does not get you a write — it gets you a denial naming the holder. Take the lock,
or wait. (An abandoned lock does not deny: nobody is writing against you. You are told, and the
takeover is still the right move.)

The script decides live-vs-abandoned by probing the holder's **pid on this host**, not by age.
The old "older than 60 minutes is a crashed run" rule was wrong in both directions — it called a
healthy 90-minute phase run crashed (and a phase run pauses on human confirmation more than once),
and it made you wait fifty minutes on a run that died after ten. Age is still the fallback when
liveness is unknowable: no pid recorded, or a lock from another host. **Never second-guess an
exit 3 by looking at `startedAt` yourself** — that is the rule the script exists to replace.

**Release** at the END of the command, including failure paths you control:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" release <name> --project <gitRoot>
```

A refusal that never acquired it releases nothing. Human-confirmation pauses (AskUserQuestion) keep
the lock — that is still your run. **Release can itself exit 3**: that means another session took
the lock over while you were working. Do not `--force` past it. Stop, tell the human, and re-read
the shard before trusting anything you wrote after the takeover.

`/audit:status` and `/audit:report` never lock and never wait for one. `audit-lock.py status`
lists what is held, with the basis for each verdict, and is read-only.

The lock directory is inside the git dir — it is NEVER committed or shown by `git status`, so no
`.gitignore` entry is needed. (The legacy `<manifestPath>.lock` fallback still wants `*.lock` ignored.)

## Branch-per-phase

Each phase gets a **local** branch so work is isolated, reviewable, and resumable.

**Parent branch rule:** a phase forks from, and merges back into, its **resolved parent** —
`phase.parentBranch ?? meta.developmentBranch` (default `main`). The same precedence chain
`reviewSkill` uses. Most phases set nothing and fork from the development branch; a phase that
sets it integrates into a story branch, a release line, or another phase's branch instead.

**Do not compose the branch name yourself.** Ask:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-branch.py" <manifestPath> --phase <phaseId>
```

It prints the parent branch, the name, and the type, each with the key that decided it. This is a
command and not a formula here because `meta.branch.template` has cases prose gets wrong: an
absent `{initials}` has to collapse **together with the separator behind it**, or the name is
`feature//p2-…` and git refuses it. Exit 1 means the composed name is not a legal ref — stop and
report, because `git switch -c` is about to fail anyway.

**Phase entry** happens on EVERY execution path (`phase`, `next`, `run`) via **Execute the task** step 1:
- **If `phase.branch` is already set** (resume/continue): `git switch <phase.branch>` if not already on it.
- **If `phase.branch` is null** (first task of the phase):
  1. Run `resolve-branch.py … --phase <phaseId>` for the parent branch and the name.
  2. **Verify the current branch is that RESOLVED PARENT; if it isn't, STOP and ask the human before branching.**
  3. `git switch -c <branch>`, then write the branch name into `phase.branch` (Edit).

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
      `sessionId` is **`$CLAUDE_CODE_SESSION_ID`** — say which one, because a session has more than
      one name and the hooks see a different id in their payload. `meter-usage` accepts either, so
      spend still lands on the claimed phase; write this one so the record is consistent.
2. Set `task.status = "in_progress"`, `task.startedAt = <ISO now>`, `task.attempts += 1` (Edit the phase's manifest file — the shard when sharded).
   If `task.attempts > (task.maxAttempts or 3)`, do NOT spawn — set `status = "blocked"` and surface to the human.
   A task entering `blocked` gets the **ADO echo** (section below).
3. **Spawn the plugin's executor agent** via the `Agent` tool —
   `subagent_type: "audit:audit-executor"`, `model = task.model`, and **`description` starting with
   the task id** (e.g. `"P3.2 shard writer"`). The id prefix is what makes token metering exact:
   every subagent gets its own transcript, and `meter-usage.py` reads the id back out of the
   spawn record — so three tasks running in parallel still get three separate token totals
   instead of collapsing to a phase average. It costs nothing and nothing breaks without it
   (spend just falls back to phase-level), so never let it block a run. Pass **only** the model;
   do **not** set reasoning effort — effort is pinned in each audit agent's own definition
   (`effort:` in its frontmatter), deliberately **decoupled from the calling session** so an
   audit's cost/latency is reproducible no matter what effort the invoking session runs at.
   (There is no per-spawn effort override anyway; the frontmatter is the only lever. On the
   general-purpose fallback below, effort cannot be pinned and reverts to the session's — an
   accepted degradation.) Its tool list is pinned (no web tools, no nested agents) and its
   system prompt carries the invariants; if that agent type is unavailable (older Claude
   Code), fall back to a general-purpose subagent and restate every rule below inline. In the
   spawn prompt:
   - Tell it to **first invoke each resolved skill** via the `Skill` tool (load conventions before coding).
     Resolve them as **each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped, area
     first** — house conventions before task specifics, because a subagent that reads the specifics
     first has already made the decisions the conventions were meant to inform. With no registered
     area this is exactly `task.skills`, unchanged.
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
        - **Stage the journal directory too** (`journal.dir`, default `<manifest dir>/journal`) if it
          exists inside `<gitRoot>`: the audit trail records the manifest writes this commit is
          carrying, and a record committed a week later cannot be checked against the change it
          describes. One file per writer per month, so parallel phases never conflict on it. If
          `journal.enabled` is false there is nothing there and nothing to stage.
        - **Completion rows are hook-emitted.** The `journal-writes` hook derives `task.complete`,
          `task.commit` and `phase.signoff` rows from your manifest writes — whichever tool made them,
          a shell command inside a `Bash` call included — NEVER append those actions by hand (two
          writers means duplicate rows and a doctor that cannot trust the count).
        - Commit with `<meta.commit.type>(<taskId>): audit - <short subject>` (use a more specific conventional
          type when it fits — `fix`, `perf`, `test`, `docs`). Append `meta.commit.coauthor` if set.
        - Capture the SHA (`git rev-parse HEAD`) and write it into `task.commit` (Edit the phase's manifest file again).
          **Do NOT write `bugs[]`.** A bug materialized into this task (`bug.taskId` ↔ `task.bugId`)
          reads as **fixed** automatically once the task is `done` — the rollup derives it (with
          `fixedIn` = this `task.commit`) — so the shared index stays untouched and parallel phases
          merge clean. (`/audit:bug close` still records a human `wontfix`/`fixed` on the index, under
          the index lock — a structural decision, not part of a run.)
        - The `task.commit` write rides along with the next task's commit (or the sign-off commit) — do NOT amend.
     d. **ADO echo** — now that the SHA is captured, echo the done transition (section below;
        an `onComplete` comment carries this `task.commit`).
   - **test failure** (gates RAN and are red) → leave `status = "in_progress"` (or `"blocked"` if attempts
     exhausted), put the reason in `task.outcome.technical`, and report it. Do not mark done, do not commit.
     A transition to `blocked` gets the **ADO echo** (section below).
   - **infrastructure failure** (gates could NOT run: missing command, runner crash before tests,
     zero tests collected where `tests.add` expects some) → this is NOT the task's failure:
     **revert the `attempts` increment from step 2** (Edit it back down), record the cause in
     `task.outcome.technical`, leave `status = "in_progress"`, and **STOP with a human action item**
     (fix `meta.buildCommands` / `tests.gate` first). Never burn retries on missing infrastructure.
5. Manual gate items (e.g. `"manual: <checklist>"`) cannot be auto-run — surface them as **human action items**.

## Phase sign-off (Definition of Done — strict order)

Run only when **all** tasks in the phase are `done`. All review/test work runs on the phase branch.

1. **`reviewResolved`** — compute the phase's changed files (union of `files` across its tasks, cross-checked with
   the manifest's top-level `fileIndex`). Resolve the review skill as
   **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** — the first level that is
   **present** answers, an explicit `null` **is** an answer (skip review), and with several tags written
   order decides. (A monorepo reviews backend vs mobile phases with different reviewers by registering
   the area once instead of repeating `reviewSkill` on every phase.) `/audit:status` prints the resolved
   value and its basis; do not re-derive it from the file if the output is in front of you.
   **If the resolved review skill is set**, spawn the plugin's reviewer agent
   (`subagent_type: "audit:audit-reviewer"`, `model = phase.review.model`) with the diff scope
   (`git diff <phase.baseRef> -- <files>`), the phase's `desiredOutcome`, and the resolved skill name — it invokes the
   skill itself and returns structured findings (it has no edit tools by design, and the diff stays out of YOUR
   context). Record results in `phase.review.findings`; for each actionable finding spawn an
   `audit:audit-executor` fix run (`model = phase.review.model`) that may edit implementation AND tests; loop until
   clean or each remaining finding is explicitly triaged with a written justification. Fall back to a
   general-purpose subagent with the same rules if the agent type is unavailable. **If the resolved review skill is
   null**, skip this step — tests are the signer.
2. **`testGateGreen`** — run the gate **through the script**, not by hand:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" <manifestPath> <phaseId>
   ```
   (run `meta.nodePreamble` first, un-piped, if set). All commands must pass **after** any
   review-driven changes. Tests are the final signer. Surface manual items as human action items.

   **It brackets the gate, and that is why it is a script (F193).** A gate is a MEASUREMENT.
   Exit 1 means one of three things and the output says which: a command failed, the gate
   **changed the working tree**, or **nothing actually ran**. Both of the last two were exit 0
   before this existed — a `pre-commit run --all-files` gate on a docs task rewrote five backend
   files and reported `Passed` *because* `isort` and `black` are fix-in-place; narrowed to the
   task's own markdown files it then SKIPPED every hook on a Python-only config and the task
   went to `done` on a gate that verified nothing.

   **`GATE MUTATED THE TREE` refuses the commit step regardless of the gate's exit code.** Do
   not commit on that run: the diff carries work no task owns and no review saw. Revert those
   files, then either use the read-only spelling of the check (`--check` not `--write`,
   `ruff check` not `ruff --fix`) or `/audit:phase retarget <phaseId> --gate <read-only entry>`.

   **`NO CHECK RAN` is not green.** A gate that skipped everything and a gate that verified
   everything are the same exit code; only the count separates them, and only runners that
   report one can be counted — where the count is unknowable the script says so rather than
   filling it in.
3. **`invariantsChecked`** — run, from the project directory and **before** the branch is deleted in
   step 5e (deleting it takes with it the reflog this reads):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/verify-invariants.py" <manifestPath> <phaseId>
   ```
   Exit 0 = no breach found · 1 = at least one · 2 = it could not be asked. It re-derives, from git
   and the shard and the journal and the usage ledger, the rules **this file states** and nothing
   enforces: a task commit staged only its own `files`, its phase's manifest file and the journal;
   no push, no forced update and no `git stash` touched the phase branch; every manifest state the
   phase committed still validates; a `risk: "high"` task ran on neither a declared nor a metered
   `haiku`; and `phase.baseRef` is on the resolved parent branch.
   **A breach is a human decision, not an automatic stop.** Print the lines it printed — verbatim,
   because each carries the SHA or the file name that makes it checkable, and a paraphrase is a
   claim with its basis removed — and ask (AskUserQuestion) whether to sign off anyway: a commit
   that carried one extra file is often explicable, a push is not.
   Lines reading `no-basis` or `partial` are **not** failures. They name what could not be checked
   (a deleted branch, an unmetered repository, a manifest state no commit preserved); read them,
   do not block on them.
4. **`runtimeBootGreen`** — **only if `meta.runtimeBoot` is set** and the phase touched app source under
   `meta.runtimeBoot.appRootPath`. Cold-boot the app and verify the primary screen renders + one navigation
   away-and-back (jest mocks and tsc miss module-init/require-cycle boot crashes). Use the runtime steps in
   `meta.runtimeBoot`; if the runtime is unreachable, STOP and hand the human an explicit boot-check action item —
   the phase may NOT be signed off until the human confirms. If `meta.runtimeBoot` is null, skip this step.
5. Only if all applicable gates pass:
   a. Set `phase.status = "done"`, `phase.review.status = "passed"` (or `"skipped"`), write `phase.review.outcome`
      and `phase.summary` (short paragraph: what was done + impact; when `phase.desiredOutcome` is set,
      the summary must state how the phase met — or didn't meet — it). **Clear `phase.claim`** if set —
      the run is finishing, release the claim. (All these are shard writes in the sharded layout.)
   b. **Sign-off commit** on the phase branch (`<meta.commit.type>(<phaseId>): phase sign-off — …`, + coauthor).
      Stage the journal directory here too, for the same reason as the task commits.
   c. **Merge into the phase's RESOLVED PARENT** (`resolve-branch.py … --phase <phaseId>` prints
      it; `phase.parentBranch ?? meta.developmentBranch`): `git switch <parent>`;
      `git merge --ff-only <branch>`.
      **When that parent is not the development branch, the sign-off report must say so** — name
      the branch the work merged into and state that it has NOT reached the development branch
      until that parent is itself merged. `resolve-branch.py` prints exactly that sentence; a
      report that stays quiet reads as "landed", which is the one thing it must not do. For the
      same reason `git branch -d <branch>` is NOT safe here while the parent is unmerged: say it
      rather than running it.
      **If ff-merge fails** (the development branch advanced during the phase — the normal case on team
      repos), ask the human (AskUserQuestion) to choose:
      1. **`git merge --no-ff <branch>`** (recommended) — preserves the phase branch history and keeps every
         `task.commit` SHA (and the `bug.fixedIn` derived from it) valid.
      2. **Stop** — leave the branch unmerged for manual resolution.
      **Never rebase the phase branch** — rebasing rewrites the SHAs recorded in the manifest.
   d. Write `phase.mergedAt = <ISO now>` (Edit on the now-merged branch). Then **ADO echo** the
      phase: its PBI (when `phase.ado` is linked) moves to the done-state (section below).
   e. Optionally clean up: `git branch -d <branch>` (safe after a completed merge).

## ADO echo (best-effort, linked items only)

The automatic half of the ADO connector. `/audit:sync` creates and reconciles links
behind its confirm gate; the echo keeps the board current between syncs by UPDATING
work items that are ALREADY linked. Contract and ADO mechanics:
`${CLAUDE_PLUGIN_ROOT}/reference/tracker-sync.md` (read it on the first echo of a run).

**Runs iff ALL of**: `meta.ado` exists · `meta.ado.enabled` is not `false` ·
`meta.ado.echo` is not `false` · the item has `ado.id`. Anything else → skip
**silently** (unlinked items are sync's business, not a warning per task).

**Hard rules** (weaker than sync, on purpose):
- **Update-only.** Never create work items, never touch unlinked items — creation is
  consent-gated in `/audit:sync push`; an echoed update inherits that consent because
  the link it updates was created under the confirm gate.
- **Never ask, never block, never retry.** No AskUserQuestion, no aborting or delaying
  the run; a failed echo is ONE report line. Two narrow exceptions, both from
  tracker-sync.md: a rejected STATE retries once without State, and a field-rule
  refusal of Remaining Work (stock processes force-clear it at done) retries
  state-only and reports the field skip.
- **One combined call per item** (`az boards work-item update` via Bash, or the
  `wit_*` MCP tools when available): state + fields + tags together. Tag writes
  READ-MERGE-WRITE the item's tag list (provenance tag from `meta.ado.tag`, absent
  = `audit-plugin`, null = none; plus `blocked` where the transition calls for it)
  — `System.Tags` updates are wholesale, and writing blind erases the team's tags.
- **No iteration stamping** — the sprint stamp is sync's job; the echo touches state,
  Remaining Work, tags and comments only.

**Per transition** (states from `meta.ado.stateMap`, defaults in the sync field map;
a `null` mapping = skip State for that transition):
- task → `done`: done-state; `meta.ado.onComplete` present → write `remainingWork`
  (default 0, explicit null = never) in the SAME call; `comments.onComplete` true →
  comment with the sign-off note and `task.commit`.
- task → `blocked`: blocked-state + tag `blocked`; `comments.onBlocked` true →
  comment with `attempts`, the last `outcome.technical` and the blockers.
- task reopened (`/audit:run` re-open, human-confirmed): pending-state + comment
  `reopened by /audit:run` — the board move inherits the reopen's confirmation.
- phase sign-off: the phase PBI (`phase.ado`) moves to the done-state.

**Manifest footprint**: bump the item's `ado.lastSyncedAt` **riding the same shard
edit the transition already makes** — never a separate lock cycle, never the index.

**Reporting**: one line at the end of the run —
`ADO echo: N updated, M skipped (unlinked — /audit:sync push to link), K failed`.
Omit the line entirely when the echo never applied (no `meta.ado`, or disabled).

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

**What NOT to lay out by hand.** The *entry view* is already rendered: run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> [--phase <id>]`
and print it verbatim. It carries the phase table, per-task status, what each pending task is
waiting on, the ready list and the bug counts — so re-tabulating any of that costs tokens for a
worse-aligned copy. The lines above are the ones a script genuinely cannot produce, because they
report events as they happen; those stay yours.

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
