# Audit orchestrator — shared execution logic

Read this FIRST from every `/audit:*` execution command (`status`, `next`, `run`, `phase`,
`review`, `resume`, `report`) together with `manifest-conventions.md`. Each command does its
own slice and defers the rules every one of them needs — config resolution, preflight,
guardrails, readiness, the lock, branch-per-phase, resume — to this file. **Execute the task**
and **Phase sign-off** are split into their own files, `reference/execute-task.md` and
`reference/phase-signoff.md`, so a command that never runs a task or never signs a phase off
does not read either: `next`, `phase` and `run` read the first, `phase` and `review` read the
second, and a command reads neither unless its own instructions say to.

## At a glance

- **Verbs:** `status`/`report` are read-only (no lock); `next`/`run`/`phase`/`review`/`resume`
  mutate (full preflight + lock + progress output).
- **Invariants (never violate):** never `git push`/force-push/`stash`; commit only a task's own
  `files` + the phase's manifest file (the single file, or its `phases/<id>.json` shard); git runs
  via `git -C <gitRoot>`, gates run from the project dir verbatim; `risk:"high"` → human confirm
  before commit (asked then, or pre-given per phase for named task ids) and never on `haiku`;
  every manifest write is re-validated; the manifest is the single source of truth.
- **A phase run:** preflight → phase branch off `developmentBranch` → Execute each ready task
  (parallel where `files` disjoint) → Phase sign-off (review? → test gate → runtime boot?) → merge
  back (ff, else confirmed `--no-ff`) → release lock.
- **On trouble:** unmet blockers → skip; gates red → retry to `maxAttempts` → `blocked`; gates
  can't run (infra) → don't burn an attempt, human action item; interrupted → `/audit:resume`.
- **One task per agent, bounded:** continuing a running agent onto its next task is preferred
  below `executor.maxHours` (default 3); at or past it, hand back with a summary and spawn fresh
  — `reference/execute-task.md`'s continuation rule.

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
  A structural write is the opposite case: it appends to the index, so two branches that each add a
  record conflict there unless the merge driver is installed (`/audit:layout merge-driver`), which
  merges by record and leaves only a genuine collision — one field changed two ways, or one id
  minted on both sides — for a human.
  **That promise belongs to `run`, not to this verb, for every verb `scripts/manifest/audit-task.py`
  exposes** (`add`, `scope`, `retarget`, `cancel`, `start`, `done`) — each takes a task or phase id from
  wherever the caller happens to be standing, so a call against phase X's id while standing on phase
  Y's branch lands in X's shard from the wrong branch, which is the merge conflict this promise says
  the layout avoids. The script prints a **warning, never a refusal** — naming both branches — the
  moment a write of its own lands this way; it stays silent when the target phase records no branch at
  all, which is most of them, and when git cannot be asked at all, since neither leaves anything to
  compare the write against.
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
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --json --section usage`
   carries `budgets.phases[]` with `spent`, `budget`, `pct` and `over` already resolved.
   **`--section` is why this is not the whole rollup.** This step needs one array and used to
   read the entire payload to reach it, which on a long-lived plan is tens of kilobytes of
   context spent per phase start. The projection is the same payload's key, not a
   recomputation of it, so nothing here can disagree with what `--json` says.
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
  stated identically wherever they are used** (here, in `reference/phase-signoff.md`'s step 1, in
  `reference/execute-task.md`'s executor spawn, in `review.md` and in `manifest-conventions.md`):
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
- **Branch operations pre-approved:** `git switch -c <glob>` and `git switch <glob>` for every glob
  `resolve-branch.py <manifestPath> --globs` prints — that is **phase entry**, and it is the only
  branch operation you still compose yourself. All other branch/checkout ops need confirmation.
  **Derive the globs, do not assume them** — a manifest using `meta.branch` has one per type
  (`feature/*`, `bugfix/*`, …) while a `meta.branchPrefix` manifest has exactly one. Guessing
  costs a confirmation prompt on every branch operation, which reads as a harness fault rather
  than a config one.
- **Merging, deleting and worktrees go through scripts, not through you.** `close-phase.py` (sign-off
  step 5) and `manage-worktrees.py` (`/audit:worktree`) own `git merge`, `git branch -d`,
  `git fetch . <b>:<p>` and every `git worktree` verb. They are pre-approved as the *script* calls
  they are. This is not tidiness: `git switch <parent>` is unavailable from inside a worktree, and
  `git branch -d` grades against HEAD rather than against the phase's declared parent — both were
  wrong in this document for as long as it existed, and neither is a rule prose can be trusted to
  remember.
- **A close never vouches for a verdict that no longer holds.** `audit-task.py done` (with
  `--commit` or `--no-change`) and `close-phase.py` ask the subject's newest recorded gate verdict
  through `_verdict_binding.close_refusal`, and refuse — naming the run — on every arm in
  `_verdict_binding.CLOSE_REFUSING_ARMS`: a red above all, and a green whose declared files changed
  after it measured them. A red recorded after the run a sign-off was bound to is newer evidence,
  and refuses the landing; a group member is asked through its carrier's run, and refused too by a
  red on its own rows newer than that run. `close-phase.py` reads the verdict at the head it would
  merge — the branch tip's committed ledger and the worktree holding the branch, and the declared
  files as committed at the tip, never a worktree's uncommitted bytes — whichever tree
  `--project` names, and asks only while the landing
  is still to happen, so a re-run over a branch already landed is never refused. A sign-off
  recorded with `--no-evidence-reason` is honoured: a stale green does not refuse its landing, a
  red recorded after that sign-off does. No recorded run at all, or an `empty-gate` answer, does not refuse: there is no
  measurement to vouch for, and the close prints so on its `gate:` line. The ways out are a green
  run recorded on the work, or `--override-verdict "<why>"`, which writes an
  `audit.verdict.close-overridden` journal row naming the run and the reason, and refuses instead
  when `journal.enabled` is false or the row will not write. The two scripts are the
  enforcement; a hand edit of `status` goes around them, and the validator does not ask this
  question.
- **Never read secrets** and **never log tokens** — enforced by the plugin's guard hooks; do not work around them.
- If `meta.nodePreamble` is set, run it (un-piped) before any build/lint/test command **you type
  yourself**. You do not need to for `run-test-gate.py`: it applies the preamble to every gate
  command it resolves, because it spawns its own shell and a preamble exported into a different one
  reaches nothing. Two gate rows once recorded exit 127, a `PATH` problem, as evidence,
  and a committed ledger carries a false failure for as long as it exists.
- Every manifest write goes through `Edit` and must keep the JSON valid — after each mutation run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` and fix any findings
  before proceeding (exit 0 = valid, 1 = findings, 2 = unreadable; `WARNING:` lines are advisory).
- **Task fields:** `commit` (SHA after task commit), `dependsOn` (task-id array), `attempts` (int, increment per
  execution), `startedAt`/`completedAt` (ISO), `risk` (`low`|`med`|`high`|null), `verifiedBy` (test names added),
  `maxAttempts` (int, default 3). Phase fields: `branch`, `mergedAt`, `desiredOutcome`. Treat missing fields as null/0.
- **`risk: "high"` tasks**: ALWAYS require explicit human confirmation (AskUserQuestion) before their
  commit — asked at the moment, or pre-given for a named set of task ids and recorded in the trail
  (`reference/execute-task.md`, step 4a) — and must **never** run on `haiku` regardless of `task.model`.
- **`attempts >= maxAttempts`**: stop retrying, set the task blocked through the verb —
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" block <taskId> --reason "<attempts
  exhausted: the last red gate's reason>"`, which writes `status` and `blockedReason` under the
  index lock with a `task.block` row — and surface to the human. Nothing refuses a hand edit of the
  status; the verb is what records why, and a blocked task with no reason cannot say when it may
  run again.

## Readiness rule

Which tasks are ready is computed, not followed: `_status_facts.ready_tasks()` lists them under
`/audit:status`'s READY NOW, `_status_facts.unmet_refs()` names what each other task waits on, and
`audit-task.py start` refuses a task with an unmet reference unless `--force --reason`, which
its `task.start` row records.

A phase becomes `done` only after `reference/phase-signoff.md`'s **Phase sign-off**, whose verb
records the verdict and then stores the status that verdict derives — `done` at once for a phase
with no branch, and at the merge, through `close-phase.py`'s `mergedAt` stamp, for one with a
branch. Do not write it by hand: `validate-manifest` warns when a stored status disagrees with
its derivation and names `audit-task.py settle`, the one command that stores every derived value
of an existing plan. Phase order
follows the manifest; within a phase, order by task id.

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

**That rule is about the FILE SYSTEM and says nothing about the machine, which is the larger
source of false failures.** Disjoint `files` keeps two executors from writing over each other;
it does nothing about the cores, the ports and the scratch directories they share. A full suite
takes all three, and two of them on one host produce reds that neither change caused — a port
already bound, a worker starved by another measurement, a fixture directory two runs both chose.
So **the gates are the part that must not overlap**: let executors edit in parallel, and run each
task's gate where no other full suite is running. `run-test-gate.py` prints a `machine:` line on
every recorded run saying whether it had the host to itself and naming the other recorded gate
runs that shared its window; on a red it also prints `claimed:`, which says whether the verdict
is this run's to claim at all. **Neither line moves an exit code** — they are observations beside
a verdict, because a rule that refused a run for having company would refuse the ordinary case
and be switched off within a day.

**A suite this plugin did not start is invisible to that line until somebody records it.** A
pre-push hook runs one on `git push`, a developer runs one in a second terminal, a commit hook
runs one — and one of those overlapping a recorded gate is where a red got attributed to the
plugin's own run. When you know such a suite ran, record it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/record-outside-run.py" \
    <manifestPath> --project <projectDir> --label "<what ran>" \
    --started <ISO> [--ended <ISO> | --duration-ms N] [--status passed|failed]
```

It writes a row with no task and no phase on it, so it can never be pointed at work or stand in
for a gate — it exists so the overlap question has something to find. **Do not try to infer one
from the spelling of a command**: reading a Bash line for the word `test` or `push` is the
guess-from-the-spelling mistake this product keeps being repaired for, and it is wrong in both
directions on the first project that wraps its own runner.

## Concurrency lock

Locks live in the **shared git directory**, not the working tree — so they coordinate across git
**worktrees/clones on one machine** AND never appear as a working-tree change (no `git status` /
hook noise).

**Do not hand-roll the lock. Run the script and read its exit code:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" acquire <name> \
        --project <gitRoot> --note "<verb> <scope>"
```

**A lock taken with this script is held BY HAND** (recorded `handedOff`), and every process of
your session is let back in under it (exit 5 inside each verb) — so under such a hold run the
verbs **one at a time, never as parallel tool calls**; two side by side are not serialised, and
the later write replaces the earlier. `_locks.held_by_us` is the rule, and nothing refuses the
parallel calls. A lock a verb takes for its own write is different: every other process waits
for it, your own session's included.

Every lock this script can take has one of these names. `index` and `usage` are the fixed
names; `phase-<phaseId>` also works — **take the narrowest one that covers your writes:**

- **`index`** — held **briefly** for STRUCTURAL writes and id allocation: `init`, `task`, `bug`,
  `sync`, allocating a new phase/task/bug id, and the phase **status-mirror** write in the index.
  Acquire → edit the index → release, within that step. The status mirror is written by the
  scripts that store a derived status, never by hand, and each takes this lock itself:
  `audit-task.py signoff` and `done` (a fixed bug's `status`/`fixedIn` too) and `settle`, and
  `close-phase.py` when its `mergedAt` stamp stores `done`.
- **`usage`** — held while the usage ledger's monthly files are rewritten by the backfill; the
  orchestrator's own verbs never take it.
- **`phase-<phaseId>`** — held for the DURATION of a phase run by `next`/`run`/`phase`/`review`/
  `resume` on that phase. Two DIFFERENT phases take two different locks → they run in **parallel**
  (separate worktrees), each writing only its own shard. A run that must also allocate an id or
  touch the index takes the index lock too, briefly (nested), then releases it.

**Exit codes are the protocol:**

| Exit | Meaning | What you do |
|---|---|---|
| **0** | acquired | proceed |
| **5** | **already yours** | this run already holds it, so proceed — and **do not release it**: the claim belongs to the hold that took it, and releasing here drops the lock out from under the step still using it. A shell reads this as 0, because "you already have it" is not a failure to take it. |
| **3** | held by a **live** run | It can be a **parallel call of your own session**: a claim a process takes for its own write is waited for by every other process, session or not. **STOP.** Print the script's output verbatim and end the command. Do not take it over. The script has already waited for it — a window sized for a lock taken for one structural write, while a phase lock is held for a whole run, so waiting longer buys the same refusal later. `--wait 0` reads the refusal at once. |
| **4** | holder is **not alive** | Print the output, ask the human (AskUserQuestion) to confirm, then rerun with `--takeover`. |
| **1** | not a git repo / cannot write | Stop and report. With no git repo there is no lock scheme at all, so there is nothing to fall back to and nothing to coordinate against: say so rather than writing as though a lock had been taken. |

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

**Release** at the END of the command, including failure paths you control — **unless the acquire
in that step answered that the lock was already yours**, in which case it is not yours to give back.
A resumed run whose own lock named a gone pid is answered `acquired` (re-recorded under it), so it
releases that lock too:

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

**Phase entry is `audit-task start`'s**, on every path that starts work — `phase`, `next`,
`run`, and a task started by hand. It was prose the orchestrator ran before the verb, so a phase
driven through the verbs never got a branch; the verb performs it now, before it writes anything:
- **`phase.branch` is null** (first task of the phase): it resolves the parent and the name through
  the same answer `resolve-branch.py` prints, and — **HEAD on that resolved parent** — writes
  `phase.branch` and `phase.baseRef`, revalidates, then `git switch -c <branch>` (the write is
  rolled back if git refuses). **HEAD on exactly the branch the plan composes for the phase** — what
  `/audit:worktree add` checks out — is recorded with its fork point as `baseRef`.
- **`phase.branch` is set**: HEAD must be on it. Anything else is refused with the `git switch` to
  make (or the worktree to start it from).
- **Refused, with the reason and nothing written:** HEAD off the parent, detached, a repository
  with no commit yet, a name git would reject, or a name already taken by a branch the phase does
  not record. On a refusal, **STOP and ask the human** — do not branch by hand to get past it.
- Outside a git repository the phase runs with no branch, and the verb says so. `/audit:doctor`
  names any running phase that has no branch.
- **The same write also claims the phase (sharded layout) and checks readiness, and both refusals
  are `start`'s**: relay either the way `reference/manifest-conventions.md` → *The operator's
  words go in unchanged* states.

**During task execution:** all edits and commits happen on the phase branch. **Push remains FORBIDDEN** — local only.

## Keeping a failed run's record (audit-state commits)

**A failed run is never committed by a task commit, and that is the whole problem.** A red gate
leaves the task `in_progress` and commits nothing; an infrastructure failure stops; sign-off only
commits once every gate is green. So `failed`, `gate-mutated`, `no-checks`, `timed-out`,
`cancelled` and `could-not-run`
evidence can sit in a working tree forever — exactly the history the record exists to keep.

**The gap is narrower than "every failure", which is why this is rare.** A task commit stages the
evidence directory, so it carries every row written since the last one: a run that fails at attempt
1 and succeeds at attempt 2 is already durable, failure included. What is not durable is a run
whose task or phase **never subsequently commits**. Run this at those points, and only those:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-audit-state.py" <manifestPath> <phaseId>
```

1. a task moves to **`blocked`** (attempts exhausted) — the main case;
2. an **infrastructure failure**, at the STOP `reference/execute-task.md`'s step 4 names;
3. a **phase sign-off gate is red** and the phase stays `in_progress`;
4. at the start of `/audit:resume`, to sweep whatever an interrupted session left behind.

**It is idempotent and safe to call when nothing is wrong** — with nothing uncommitted it makes no
commit and says so, so calling it spuriously costs a line of output. It stages the phase's manifest
file, the journal and the evidence directory and **never the task's `files`**: the implementation
stays unstaged, which is what makes committing a failed task's *state* possible at all.
`verify-invariants.py`'s `audit-state-scope` grades those commits afterwards, and a staged
implementation file is a breach.

**Do not run it from a signal handler or an interrupt path.** A cancelled run records its row
locally and returns; trigger 4 is what makes that row durable later. Git belongs to the
orchestrator, and a commit made while stopping is how a half-made one happens.

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

## Answering one question about the trail

A handful of questions come up repeatedly and each has exactly one answer, carried by a pointer
a reader can check: why a task or phase was cancelled, what a bug concluded, which task last
touched a file, which task(s) last touched every file ONE task itself declares (folded from the
file question), and what a recorded gate run answered. None of them needs the whole plan or the
whole journal read to answer — that cost grows with the project instead of with the question,
and the file question (and the brief question built from it) is a **lookup**, not a search:
`fileIndex` already records who declared what.

```
scripts/status/audit-lookup.py <manifest> cancel <taskOrPhaseId>
scripts/status/audit-lookup.py <manifest> bug <bugId>
scripts/status/audit-lookup.py <manifest> file <path>
scripts/status/audit-lookup.py <manifest> brief <taskId>
scripts/status/audit-lookup.py <manifest> run <runId|latest> [--phase <id> | --task <id>]
```

Run it and relay its answer — do not re-derive the same fact by grepping the manifest or the
journal by hand once this exists to answer it. **A match that finds nothing says so** (exit 1)
and never returns the nearest id or a similar path as if it had answered; an id that exists but
does not apply to the question (a task that was never cancelled) is a different, legitimate
answer and not a miss.

**`run` reads the evidence ledger, not the manifest or the journal — it is what a background
gate's verdict is read back from.** A gate expected to outlast the Bash tool's foreground bound
runs under `run_in_background`, so its own terminal may never be read to the end; the run
records its row in the ledger **before** it prints anything (`--record`'s row write happens
strictly after the measurement completes and strictly before the banner), so the verdict is
never lost to a truncated terminal. Read it back with the `runId` the run's own `evidence:
recorded <runId>` line named, or with `run latest --phase <id>` / `run latest --task <id>` when
that id was not kept. **Never read a background gate's verdict off a truncated terminal** — the
ledger row is what the recording already made durable, and it is a lookup rather than a search.

**`brief` is the one of these you do not wait to be asked.** `cancel`/`bug`/`file` answer a
question a human or a reviewing agent puts to you; `brief` answers the question an EXECUTOR
would otherwise grep the manifest or the journal for at the start of its own task, so it is run
by you and folded into the spawn prompt before that agent's first turn —
`reference/execute-task.md`'s step 3 says where. Exploring the tree for a fact the plan already
carries is then a deliberate step the executor justifies in its outcome, not its default first
move.

This is a narrower tool than the **Resume after interruption** procedure below, which asks a
different question — *which phase is resumable* — and still needs the manifest read in full for
that.

## The third place

`meta.fullGate` names a gate beyond a task's own and a phase's sign-off gate — the whole
product, measured with `run-test-gate.py --full --record` or the one command
`scripts/governance/full-gate.py` wraps around it, never one phase's or one task's claim.
**A phase that merges is `provisional` until that third place records it, and provisional
blocks nothing inside a session.** It already shows on `/audit:status`, the report and the
panel, so whoever reads any of those already knows a phase has landed without yet being
`whole`; only this repository's own release guard turns a provisional phase into a refusal,
and that refusal belongs to the release command, never to a phase run.

**Never claim a full run passed, or that a phase is whole, from anything but the ledger.**
`_evidence_io.full_status` is the one answer every surface reads. It answers `whole`,
`provisional`, `unknown` or `not_declared`, derived from the evidence ledger alone, never from a
manifest pointer or a memory of what a gate answered earlier in this session. Read a recorded run back with `scripts/status/audit-lookup.py <manifest> run <runId>`,
exactly as **Answering one question about the trail** above describes, rather than asserting
what a run answered from its own printed lines.

**A full run expected to outlast the Bash tool's foreground bound follows the same background
rule a phase gate does**: run it under `run_in_background`, and read its verdict back from the
ledger once it has recorded — never from a truncated terminal.

### What a red full run teaches

**`full-gate.py` is the part of the third place that learns; `run-test-gate.py --full` alone
does not.** The runner prints one `SELECTION MISS:` line per suite it named failing that no
derived sign-off gate listed, among the phases merged since the newest earlier **measured** full
run — green, clean and verbatim against the declared gate, whether or not its row names a tested
head (`_evidence_io.newest_measured_full_run`). With no such run to bound "merged since", or one
whose row names no head to ask ancestry of, nothing is asked and a `SELECTION MISS not asked:`
line gives the reason; so does a ledger read with losses, naming the file, because the bounding
run may sit on the line that read lost. Each suite name is first pinned to the one tracked file it
names (`_evidence_io.pin_suite`); a name that fits none or several is never counted as listed and
prints `SELECTION MISS not asked of <name>: <why>`. Each miss line ends either in the commands
that would file it — `python3 <plugin>/scripts/manifest/audit-task.py couple … <manifest>
--project-dir <project>` and the matching `bug-add`, every path absolute and shell-quoted so they
run as printed from any directory, printed and never run (`run-test-gate._miss_remedy`) — or in
the reason none can be printed. `full-gate.py`, after a red exit, reads the row
that run recorded and runs those verbs itself, as subprocesses (`full-gate.learning_plan`):

- a `couple` (the suite to the sources the miss names) and a `bug-add` titled
  `SELECTION MISS: <suite>` for each `selectionMiss` entry, filed under the suite's pinned path;
  a name that pins to no tracked path, or to several, still files its bug, with no `--files` and
  no coupling;
- a `couple --caught <runId>` for each suite the plan already coupled that the runner named
  failing, which refreshes that coupling's `lastCaught` — never for a suite the row lists in its
  own `selectionMiss`, which says no derived gate ran it, so a coupling that row creates or
  widens, or that another row with the same miss taught, is not its catch.

Each verb's lines and exit code are printed, and the exit stays the runner's — a run that taught
something is still a red run. Its closing line, as a red run printed it:
`[full-gate] the run is still red - exit 1 from run-test-gate.py blocks the push, whatever was
learned`.

**Only a suite the runner named teaches.** Every miss is asked again through
`_evidence_io.named_failing_suites`, which counts a suite only when the step's
`failingSuitesBasis` says the runner named it, and never counts a muted step. A failure read off
the tail of the output, a run the runner printed `evidence: NOT recorded` for, and a green run
teach nothing, and a red run that taught nothing prints a line per reason. A miss whose `sources`
the row cut (`sourcesDropped`) files its bug but no coupling, because a suite coupled to a
prefix of what it depends on is narrowed where nobody sees it. A push retried on the same red
does not file the same bug twice (an open bug with that title is skipped) or re-send a coupling
that already covers every source named.

**A catch is credited to the coupling a name pins, or to none.** A runner may print a suite
relative to its own directory, so each name it gave is resolved against the plan's coupled
suites by `_evidence_io.resolve_named`: a name matching exactly one is that coupling's catch, and
a name matching several credits none of them and says so (`no catch credited for …`). The
couplings are read before anything this run writes, so a suite coupled by this run is not also
credited with a catch by it. `couple --caught` asks the same questions again on its own and
refuses a run that is not `full`, a suite the run did not name or named only on a muted step,
and an ambiguous name; a catch no newer than the recorded `lastCaught` writes nothing, so
`lastCaught` never moves back.

**A red full run CI recorded is learned from after its shard is imported, never inside the
pipeline.** A CI build throws its checkout away, so the pipeline records (`run-test-gate.py
--full --record --writer ci-<id>`) and files nothing. `import-evidence.py <manifest>
<shard.jsonl>` writes into the manifest's own project (`_panel_write.project_of_manifest`), never
the directory it was typed in, and refuses, exit 2, a manifest outside a `--project-dir` it is
given. It prints, for each imported row that is full scope and red, the command
`python3 <plugin>/scripts/governance/full-gate.py <manifest> --learn-from <runId> --project-dir
<dir>` with every path absolute, so it runs as printed from any directory, and runs none of
them. That command runs no gate: it reads the row from this checkout's ledger and hands it to
`full-gate.learn_from_row`, the function the red branch calls, so every rule above applies
unchanged, whatever order the rows are learned in. It refuses, exit 1, a run id the ledger does not hold (naming any ledger file
it could not read in full), a row that is not full scope and a green row; it exits 1 when a
learning verb fails, and 2 beside `--writer`. `/audit:review <phaseId> --full` runs
`full-gate.py` itself, so a red run there is learned from on the spot. Run the printed command
after an import when the operator asks for the import; nothing runs it for you, and
`/audit:review` does not.

**Removing a coupling is `audit-task.py uncouple --test <path>`, typed by a person.** No code
path removes one on its own: `learning_plan` builds only `couple`, `bug-add` and
`couple --caught`, and `/audit:doctor`'s coupling row names candidates with the `uncouple` command
and runs nothing. Leave that command to the operator the doctor row addresses — nothing stops
an orchestrator from typing it, so this sentence is the whole of that rule.

### Quarantine: `meta.muted`

A mute names a suite whose failure a bug already tracks. **A muted suite is run and recorded,
never blocks while its mute holds, never teaches, and blocks again once its `until` has
passed:**

- **Run and recorded.** Nothing is skipped: the mute is judged after the step ran
  (`run-test-gate.mute_decision`), the step keeps its exit and the names that failed, and it
  carries a `muted` marker on the evidence row. The terminal prints
  `muted: <suite> failed (bug <id>, until <day>)` under the step.
- **Never blocks.** A step whose whole failure a live mute covers is left out of the failed
  steps (`failed_steps`), so the run can pass.
- **Never teaches.** `named_failing_suites` skips a muted step, so `full-gate.py` files no
  coupling, no bug and no catch from it, and `couple --caught` refuses one.
- **Blocks again after `until`.** `until` is the last UTC day the mute holds
  (`_manifest_vocab.mute_expired`); past it the runner stops honouring the entry and prints the
  failure as blocking, and `validate-manifest.py` warns with the `unmute`/`mute` commands.
- **Blocks in its own bug's fix task, and once its bug is closed.** `run-test-gate.withheld_mutes`
  refuses, whatever `until` says, the mute of the bug whose `taskId` is the task under `--task` —
  that task's gate must show the failure cleared, so a fix task's gate is never quarantined by its
  own bug — and the mute of any bug closed by its effective status, which `validate-manifest.py`
  warns about (`rules.muted.bug-closed`) with `audit-task.py unmute --test <path>`.

**The mute fails closed.** It holds only when the runner named every failing check and every file
it blamed, a live entry covers each of those files, and `mute_ineligible` finds the step to be one
direct call of a runner on `run-test-gate.MUTE_RUNNERS` — read by `command_runner` — that exited
with that runner's failed-tests code, printed exactly one runner's summary, tallied as many
failures as it named, reported nothing else failing, did not stop early and failed no coverage
threshold. A package script, a task runner, a script file, a compound command or a runner off the
list keeps the gate red, with the reason printed on the `muted:` line. `MUTE_RUNNERS`' own comment
names a failure a direct call cannot show: a jest reporter error exits with jest's
failed-tests code and prints nothing, so a mute beside it still holds.

**No retry until green.** `run-test-gate.py` gives a step a second attempt only when the
operating system killed it, as read by `ended_by_signal`, from the exit status, or by
`jest_worker_signal`, when jest's own report names every failure as a worker the operating
system terminated. A single test failure beside such a kill is a verdict and keeps the step
failed, so a red that a test reported is not rolled again. A Playwright `flaky` test is recorded as an observation on the
step, never as a retry this plugin made, and a flaky count beside a muted failure refuses the
mute. `mute` and `unmute` (`audit-task.py`) are the only writers of `meta.muted`, and a mute naming
no bug in `bugs[]` is a validator finding, so a quarantine cannot be written to turn a red phase
green without a tracked bug behind it.

## Resume after interruption

1. Read the manifest. Find the phase with `status == "in_progress"`, a non-null `branch`, and no
   `mergedAt` — a phase whose branch already landed has nothing left to resume, whatever `status`
   still says: `close-phase.py` stamps `mergedAt` the moment the merge is verified and never writes
   `status` itself, so a merged phase can sit at `in_progress` indefinitely without being one.
   **Pre-0.3 manifests fallback:** if no such phase exists, use the phase with a non-null `branch`,
   no `mergedAt`, and status != `"done"`, else the phase containing an `in_progress` task. If none of
   these exist, report "nothing to resume" and suggest `/audit:status`. Otherwise `git switch` to its
   branch.
2. Compare committed work: `git log --oneline <phase.baseRef>..HEAD`.
3. Find the resume point: the **first task whose `commit` field is null/missing**:
   - `status == "done"` but no `commit` → the commit step was interrupted; re-commit its files now (standard message, record SHA).
   - `status == "in_progress"` and no `commit` → working-tree changes are **untrusted**; run `git status`. If complete and
     gates pass, finish + commit; if partial, **ask the human** whether to discard (`git checkout -- <files>`) and re-run.
     Never discard without confirmation.
   - `status == "pending"` → resume normally: read `reference/execute-task.md` and follow
     **Execute the task** — whose step 1/2 cover what to do on a readiness or claim refusal from
     `start`.
4. Continue normal execution from the resume point — reading `reference/execute-task.md` and, once
   every task in the phase is `done`, `reference/phase-signoff.md` when you reach them, rather than
   up front: a run that resumes into a `done`-but-uncommitted phase or a fully-blocked one may need
   neither.

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

**A phase run is not finished while its lock is held and a task is ready.** Between waves that is the
only thing that decides whether you are done: re-read the ready list before ending a turn, and if it
is non-empty the run continues — naming the next wave is not running it.
`/audit:status --gate --fail-on unfinished-run` asks the same question from outside, and it fails a
run that stopped here. This is written down because it happened: a run with twenty ready tasks
committed wave 1 of eight, reported which four came next, and sat idle for a day with its lock still
held and nothing refusing anything.

**What NOT to lay out by hand.** The *entry view* is already rendered: run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --short`
and print it verbatim. It carries the overall line, the usage line, the ready list — each entry
with the command that runs it — and the open-bug count, closing with the command that shows the
full table — so re-tabulating any of that costs tokens for a worse-aligned copy, and the phase
table this echoes between waves is not what that reader needs paid for again; `/audit:status`
still renders it whole, typed. `commands/next.md` and `commands/phase.md` print their own, wider
entry view instead of this default — `next` because its next step reads the full table's
`waiting on` column, `phase` because it scopes to one phase — so neither takes `--short` here.
The lines above are the ones a script genuinely cannot produce, because they report events as
they happen; those stay yours.

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

**Report when the command's contract is DISCHARGED, and not before.** This section used to open
with "after any mutating command", which is the sentence that lost a run: `/audit:phase` had 20
ready tasks in 8 waves, wave 1 committed, the summary named the next ready tasks exactly as this
section prescribes — and the run stopped there and sat idle for a day. Nothing had gone wrong.
Printing "the next ready task(s)" is what a FINISHED command does, so writing it mid-loop makes an
unfinished run look complete to everyone including the model writing it.

So the trigger is the contract, not the turn:

- **`/audit:phase <id>` is discharged** when no task in the phase is ready AND sign-off has run.
  A wave completing discharges nothing. **A turn boundary is not a stopping point** — neither is a
  commit, a green gate, or a convenient place to summarise. If tasks remain ready, the next thing
  you do is launch them.
- **`/audit:run <id>` is discharged** when that task is `done`, `blocked`, or stopped at a human
  action item.
- **A progress note between waves is something you emit while CONTINUING**, never instead of
  continuing. Make the remainder visible in it — `wave 2 of 8 — 16 of 20 tasks still ready` reads
  as an unfinished job, where `next up is wave 2` reads as a plan somebody else will action.

Then print the final summary: tasks completed this run (with one-line outcomes), the
phase sign-off result if reached, and the next ready task(s) (`/audit:next` / `/audit:phase <id>`). Keep
the manifest the single source of truth — never track status elsewhere. Release the lock.

**Stopping early is legitimate in exactly the cases this document names** — attempts exhausted, an
infrastructure failure, a red sign-off gate, a `risk: "high"` confirmation, a budget at or over
100%. Each has its own step and its own words. If none of them fired, the run is not finished and
there is nothing to report yet.
