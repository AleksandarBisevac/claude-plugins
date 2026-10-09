# Manifest conventions

Shared rules for every command that reads or mutates the audit manifest
(the `/audit:*` execution commands plus `/audit:init`, `/audit:task`, `/audit:bug`,
`/audit:propose`, `/audit:sync`).
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>
```

Exit 0 = valid. On findings: fix the manifest and re-run before doing anything else.

## Concurrency lock

Locks live in the **shared git dir**
(`$(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks`), not the working
tree — so they coordinate across worktrees and never show up in `git status`.
The full protocol and the two tiers (index lock vs per-phase-shard lock) are in
`orchestrator.md`. The structural commands here — `init`, `task`, `bug`,
`propose`, `sync` — take the **index lock** (they mutate the shared index: phase
directory, `bugs[]`, `proposals[]`, `fileIndex`, id counters). Before your
**first** index write:

1. Take it with the script — never by hand:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" acquire index \
           --project <gitRoot> --note "<command>"
   ```
   **0** → proceed. **5** → you already hold it: proceed, and release nothing —
   the claim belongs to the hold that took it. **3** → another run is mutating
   this manifest and the script has already waited for it: print the output and
   STOP. That run can be **your own session's parallel call** - a verb takes the
   index lock for its own write, and another process of the same session waits
   for it and is refused once the wait runs out. **4** → the holder is not alive:
   ask the human (AskUserQuestion) to confirm, then rerun with `--takeover`.

   **Under a hold taken this way, run the verbs one at a time, never as parallel
   tool calls.** A claim taken by hand with `audit-lock.py acquire` is recorded
   `handedOff`, and every process of the session that took it is let back in
   (exit 5 inside the verb) - so two verbs run side by side under it are not
   serialised, and the later write replaces the earlier. `_locks.held_by_us` is
   the rule; nothing refuses the parallel calls.
2. **Release** at the END of the command, including failure paths you control —
   unless the acquire answered **5**:
   `audit-lock.py release index --project <gitRoot>`. AskUserQuestion pauses keep
   the lock (still your run). A release that exits **3** means you were taken
   over — stop and tell the human rather than `--force`-ing past it.
3. **Read-only subcommands never lock** (`/audit:bug list`, `/audit:sync status`
   perform no write). The lock dir is inside the git dir → never committed; no
   `.gitignore` needed. (No git repo? there is no lock scheme at all — say so
   rather than writing as though one had been taken.)

`/audit:init` **regenerate/append** is the most destructive write — it rewrites
the whole manifest. It MUST hold the **index lock**, refuse while another
session's lock is fresh (never clobber an in-flight run), and back up before
overwriting.

## ID allocation

Allocate ids **while holding the index lock** (see `orchestrator.md` → Concurrency
lock): read the current maximum from the assembled manifest, add one, write, release —
so two sessions on one machine can never mint the same id (the lock serializes the
read‑modify‑write). **Never compute an id by hand**: the verbs that write a record
allocate its id (`/audit:task add`, `/audit:phase add`), and a record a command writes by
hand takes it from `audit-task.py next-id bug|prop|task --phase <id> <manifestPath>`.

**Off the development branch an id carries a branch suffix**, so two branches cannot mint
the same one: `BUG-12-k7m`, `P60.6-k7m`, `PROP-3-k7m` - three `[0-9a-z]` characters drawn
from the branch name. On the development branch (`meta.developmentBranch`, default `main`),
on any branch a phase names as its parent, and on the branch `origin/HEAD` names, ids are
exactly what they were. The number ignores the suffix, so ids keep their order.

**Phase ids carry no suffix, because phases are minted on the development branch.** A phase
id is a branch name, a lock name and a shard name. New work found on a phase branch is parked
as a proposal (`/audit:phase add ... --park`), which reserves the placeholder `P<n>-<suffix>`;
`/audit:propose materialize` on the development branch mints the real `P<n>` and renames the
placeholder and every reference to it.

**What the suffix cannot prevent** - two clones minting on the development branch itself -
reaches the merge, which names the id; `merge-manifest.py resolve <manifestPath> --renumber
ours|theirs` (`/audit:layout merge-driver`) renumbers the side the user names, with every
reference. Without the merge driver, `validate-manifest.py`'s repo‑wide unique‑id check
catches a duplicate after merge, and `/audit:layout <sharded|single-file> --renumber`
repairs duplicate bugs.

- **Task**: `<phaseId>.<n>[-suffix]` where `n` = highest existing number in that phase + 1 (`P2.4` → next is `P2.5`; `P2.5-k7m` on a side branch).
- **Bug**: `BUG-<n>[-suffix]` where `n` = highest existing bug number + 1, repo-wide (`BUG-3` → next is `BUG-4`).
- **Bugfix phase**: `BF<n>` where `n` = highest existing `BF` number + 1 (`BF1`, `BF2`, …).
- **Proposal**: `PROP-<n>[-suffix]` where `n` = highest existing proposal number + 1, repo-wide.
- **Decision**: `DEC-<n>` where `n` = highest existing decision number + 1, repo-wide.

Phases, tasks, bugs and decisions share **one** id namespace — `blockedBy` resolves
against phase, task and decision ids together, so two of them wearing one id make every
reference to it ambiguous. The validator reports a duplicate across all four.

The "highest existing" is computed over the **whole** manifest — every phase shard plus
the index — which the `/audit:*` commands already load assembled (so a task suffix sees
every task in its phase, and a `BUG-`/`BF` number sees every bug/bugfix phase repo-wide).

**Reserved ids.** A still-parked proposal (`status: "proposed"` with a payload)
RESERVES its `payload.phase` id and task ids: `P<n>` allocation counts them
alongside live phases, so materialization is a lossless move and inter-proposal
`blockedBy` refs stay meaningful. Materialized and dropped proposals release
their reservations (a materialized payload id IS the live phase; a dropped one
is free to re-mint).

## Status enums

- Phase/task: `pending | in_progress | blocked | done`
- Bug: `open | triaged | in_progress | fixed | wontfix | not_a_bug` — the last three
  all close it and say different things: the fix landed, the report is real and will
  not be fixed, somebody investigated and the behaviour is correct
- Proposal: `proposed | materialized | dropped` (enforced on payload-bearing
  proposals; legacy free-form entries are tolerated as-is)
- `tests.mode`: `tdd | regression | gate-only` · `risk`: `low | med | high`

## New task template

Every newly created task MUST be initialized with ALL of:
`status: "pending"`, `attempts: 0`, `maxAttempts: 3`, `commit: null`,
`outcome: {technical: null, descriptive: null}`, `startedAt: null`,
`completedAt: null`, `verifiedBy: []`, plus explicit `blockedBy: []` /
`dependsOn: []` (empty when none) and a `tests` object with `mode`, `add`,
`expectRedFirst`, `gate`.

**`tests.gate` is the task's own scope, not a copy of the phase's.** The phase gate is
wide because its question is wide, and a task gate is narrowed to the task's own files —
a wider one does not answer its question any better, it answers the PHASE's question
again, once per attempt, per task, per phase running in parallel. `commands/init.md` →
step 5.3 is where a plan's gates are derived; `/audit:task add` derives one the same way
for a task added later and prints which default it took (`reference/verbs-in-full.md` → *The task
gate is derived*).

**Every `tests.add` entry is written `"<path>: <what it asserts>"`**, the path being
the repo-relative file the case will live in — even when it does not exist yet. That
leading path is what `/audit:task add` and `scope` carry into the task's `files` and
the `fileIndex`, so an entry opening with prose puts nothing there and leaves the case
file outside the scope commit-scope grades the task against. On a `tdd` task that is
not yet `done` or `cancelled` the validator **refuses** an entry naming no file
(`COMPATIBILITY.md` → *Validation stays additive*). For `regression` and `gate-only`
the shape is recommended, not required.

**`testEvidence` is deliberately NOT in that list**, and its absence is the fact rather than an
omission: it is written by the recorder when a gate actually runs, and absent means *no run has
been recorded*, which is a different claim from every value it could be initialized to. The same
goes for a phase. Nothing initializes it, nothing needs to, and a hand-written one would name a
`runId` that resolves to no row in any ledger.

## New phase template

A newly created phase MUST be initialized with: `status: "pending"`,
`baseRef: null`, `branch: null`, `mergedAt: null`,
`review: {tool: null, model: "sonnet", status: "pending", findings: []}`,
`summary: null`, a one-line `desiredOutcome` (what success looks like — `/audit:status`
shows it, task subagents receive it, and sign-off must address it), and a
`testGate` derived from `meta.buildCommands` keys. Optionally `reviewSkill` (a phase-specific
sign-off reviewer, overriding `meta.reviewSkill`) and `area` — a label, or a **list** of
labels for cross-cutting concerns (`"backend"` or `["backend","security"]`; any vocabulary —
devops/security/embedded/data/ml/…) — for grouping/filtering in status/report/panel. Both default to absent.

`review.readReturns` is never initialized. `audit-task.py signoff` writes it with the verdict: one
`{return, sha256}` row per filed phase return that sign-off read, so `close-phase.py` can refuse a
return needing a human that the verdict never read, wherever it was filed. Absent means a verdict
written before the field, which the landing reads by where each return sits.

A human's settlement of such a return binds the answer it settled, not the return's name. The
driver's state (`<stateDir>/drive/<phase>.json`, outside the plan) records it under
`answersAccepted`: `keys` names each settled answer, and `signatures` holds one `{key, sha256}`
entry per answer, the sha256 being the signature of the return the answer sits in - the same
signature a `readReturns` row records. The sign-off verb, which writes `readReturns`, and
`close-phase.py` over a verdict recording it honour a settlement only for a return carrying the
signature it records; a key recorded without one settles nothing there, and only the landing of a
verdict recording no `readReturns` still reads `keys` alone.

## Phase priority (`phase.priority`)

An optional positive integer saying which phase to reach for first **among the tasks
that are already ready**. It never makes an unready task ready and never skips a
dependency — a pinned phase whose `blockedBy` is unsatisfied is skipped, and
`/audit:status` prints the note naming what it waits on and which task ran instead.

- **Tier 1 is unique.** Higher tiers are shared. A second holder of tier 1 is refused at
  write time (the refusal names the current holder), and if one is forced anyway the
  validator warns and the phase that comes FIRST in the manifest wins.
- **Absent means unprioritised** — not tier 0, not a middle tier. Such a phase sorts after
  every pinned one and keeps its written position among its peers, so a manifest with no
  `priority` anywhere runs exactly as it always did.
- **Never hand-write it.** `/audit:phase priority <phaseId> <tier|--clear>` takes the index
  lock, revalidates and journals a `phase.priority` row; hand-editing loses all three.
- **Index-only in the sharded layout.** It belongs on the index stub — which already carries
  `status`, so the order is computable without opening a shard, and one writer under one lock
  means two parallel phase runs can never collide on it. A copy found in a shard body is
  ignored, and the validator reports that it was.
- **`priority.maxTier`** (`.claude/audit.config.json`) is advisory. Nothing is clamped to it.

## Areas (`meta.areas`)

A tag on a phase groups it. Registering that tag in `meta.areas` gives it properties:

```json
"areas": {
  "api": {"root": "services/api", "description": "Django service",
          "reviewSkill": "backend-review", "skills": ["python-conventions"]},
  "mobile": {"root": "apps/mobile", "description": "Expo app"}
}
```

`root` is relative to the **project dir**, the same origin as `task.files` and the `fileIndex`
keys (so it carries the `meta.gitRoot` prefix when the workspace is in a subdirectory).

**Registration is optional in both directions.** A phase tag with no entry stays legal — free text
is the v0.16 behaviour and is not deprecated; the validator warns only when the manifest registers
areas at all, where an unregistered tag is nearly always a typo. An entry no phase uses is legal too.

Two things resolve against it, and they are **stated identically here, in `orchestrator.md`'s
config resolution, in `execute-task.md`'s executor spawn, in `phase-signoff.md`'s step 1, and in
`review.md`**:

- **Review skill** — `phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`. The
  first level that is **present** answers, and an explicit `null` **is** an answer (skip review;
  tests are the signer) rather than a fall-through.
- **Executor skills** — each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped,
  **area first**.

When a phase carries **several tags**, WRITTEN ORDER decides: the first tag whose area declares the
field answers. `/audit:status` prints the resolved reviewer with the basis it came from
(`review: backend-review (area api)`), and `/audit:doctor` warns when a root is not a directory or a
phase tag has no entry. Never re-derive any of this by hand when the output is in front of you.

An area may also declare an advisory **`owner`** (v0.34) — who to coordinate with, written the
way `usage.authorMode` records authors (git `user.email` under the default mode). An explicit
`null` is an answer ("nobody owns this"), not a fall-through, and across several tags written
order decides here too. Advisory only: when someone else edits a covered file in an owned area,
the plan gate adds a once-per-session heads-up; `/audit:status` and the panel display the owner;
nothing gates on it and nothing is assigned by it.

## Proposals (parked phases)

`proposals[]` holds phases that were synthesized but not (yet) approved —
`/audit:init`'s park path writes them, `/audit:propose` lists/materializes/drops
them. A payload-bearing proposal is:

```json
{"id": "PROP-1", "name": "<phase title>", "status": "proposed",
 "origin": "audit:init", "createdISO": "<ISO>",
 "scope": "<main dirs>", "benefit": "<desiredOutcome>", "openQuestions": [],
 "materializedAs": null, "materializedAt": null,
 "payload": {"phase": { ...the full phase... }}}
```

Rules:
- `payload.phase` must be **fully template-initialized** (new-task + new-phase
  templates above) so materialization is a move, not a rebuild.
- The payload's phase/task ids are **reserved** while parked (see ID allocation).
- `fileIndex` covers **live** tasks only — parked tasks enter it at materialize
  time, derived from `payload.phase.tasks[].files`.
- `materializedAs`/`materializedAt` are written by `/audit:propose materialize`
  together with `status: "materialized"` — never by hand, and the record is kept
  as history (like closed bugs).
- Legacy free-form entries (no payload) are tolerated: the validator warns at
  most, `/audit:propose list` renders them with `-` columns, nothing can
  materialize them.

## Decisions (`decisions[]`)

`decisions[]` is where a decision ABOUT the plan is recorded, so an approval is held
where the work is planned instead of in a conversation, a note or a commit message. A
refusal that has nowhere to read a prior answer from has to stop and ask a human every
time it is reached; with a row, it reads the record.

```json
{"id": "DEC-1", "title": "<the question, so a reader knows what was asked>",
 "status": "pending", "question": "<longer form, optional>",
 "answer": null, "decidedBy": null, "decidedAt": null, "notes": null}
```

Rules:
- **`status` is the phase/task vocabulary**, not one of its own: `pending` = asked and
  unanswered, `done` = answered, `cancelled` = it will not be answered. That is what
  makes a decision safe to name in `blockedBy` — one resolver settles every kind, and a
  private vocabulary would be a blocker nothing could clear.
- **`answer` and `decidedBy` are REQUIRED once `status` is `"done"`** and the validator
  says so by name. An approval with no words is the second-hand approval the row
  replaces, and one nobody is named for cannot be held to anyone. An *unanswered*
  decision is allowed to be unanswered — that is its whole purpose.
- A task or a phase waits on one by naming it in `blockedBy`; readiness treats `done`
  and `cancelled` alike, so nothing deadlocks on a question that will not be answered.
- `files` on a decision is **informational**. A decision opens no file, and the plan gate
  reads task `files` and `outputs` alone.
- **A dependency on another session is NOT a decision and gets no row.** It has no status
  anything here can settle, so naming one in `blockedBy` stays a validator finding rather
  than resolving to something that never clears — a dependency that cannot be cleared is
  a row that lies about what the plan is waiting for. Set the task blocked with the
  dependency as its reason — `/audit:task block <taskId> --reason "<what it waits on>"`,
  which writes `status` and `blockedReason` together with a `task.block` row — and record
  what changes with `/audit:task note <taskId> --text "..."`. Not the `description`: once
  the task has started, `scope --description` refuses it, because the brief is what its
  attempts were judged against.

## What a `files` entry covers

An entry covers itself and everything under `entry/`, with or without a trailing slash
(`src` and `src/` both cover `src/a.py`); a sibling that only shares a prefix (`src-old/a.py`)
is not covered, and a `:line-range` suffix is ignored. One predicate, `_task_outputs.covers`,
decides this for the plan gate, the shell and secret guards, and the TDD nudge.

## Task outputs (`task.outputs`)

`files` is what a task **edits** and every entry owes a `fileIndex` row. `outputs` is what
a run **produces** — the documents it writes, an evidence directory, a generated report —
which cannot be enumerated before the run makes them, so it is patterns:

```json
"outputs": ["docs/audit/evidence/**", "docs/reports/*.md"]
```

While the task is `in_progress` the plan gate treats a write matching one of these as
covered by it, which is what stops a documentation write being reported as uncovered on
every save — and a gate whose warnings are noise is a gate that is off.

**Every pattern's first segment is a literal directory name.** `docs/**` is accepted;
`**`, `**/*.md`, `.`, `*/x`, an absolute path, a `~` path and anything with a `..` segment
are refused by name, at the writer and at the validator alike, because a task covering the
whole tree would turn the plan gate off through the door built to keep it on. `**` spans
directories, `*` stays inside one, and a trailing `/` means the same as `/**`.
`/audit:task add --outputs a,b` is the door; there is no widening verb, deliberately —
`scope`'s apparatus is written about `files`.

## fileIndex maintenance

Adding a task with `files` MUST add/extend the matching top-level `fileIndex`
entries (`"<file>": [..., "<taskId>"]`). Never remove other tasks' ids.

## Immutable history

Phases with `status: "done"` are history — never append tasks to them.
Route new work to an open phase or create a new one.

## Moving a task (`/audit:task move`)

`/audit:task move <taskId> --to <phaseId>` is the only sanctioned way to relocate a
task, and it is a script call (`audit-task.py move`), not a hand procedure. It allocates a
fresh `<targetPhase>.<n>` id under the index lock with the allocator `next-id task` prints
(counting reserved proposal ids), writes `movedFrom: {id, phase, at}` on the task, rewrites
every `blockedBy`/`dependsOn`/`fileIndex`/`bugs[].taskId` reference across the index, all
shards and the parked proposals, revalidates (rolling back on findings), and appends a
chained `task.move` journal row with `{fromId, toId, fromPhase, toPhase}`. A hand-drag keeps the old id, which the validator
flags (`id does not follow its phase's prefix` — a warning, never a finding).

**Ledger attribution:** historical usage-ledger rows keep the OLD taskId — history is
never rewritten. New spend attributes to the new id. `movedFrom` plus the `task.move`
row are what let a reader join the two halves.

## The operator's words go in unchanged

Every value a command gathers from a human and hands to a script — `--reason` on a
cancel or a drop, a close note, a sign-off note — reaches the manifest **and the
hash-chained journal**. Pass it through **VERBATIM**. Do not tighten it, expand it,
smooth it, or translate it.

**Why this is a rule and not a preference.** The journal's whole claim is
tamper-evidence: rows chain, a hook fires when a shell command touches the file, and
`audit-journal.py verify` reports the chain clean. All of that works on whatever
sentence it is given. Paraphrase the operator and the trail then *cryptographically
guarantees a sentence its subject never wrote* — which is worse than no record,
because a reader has every reason to trust it.

Measured, live: the operator answered **"Tracked in ADO only, not executed here"** and
what reached the script was *"tracked on the board only; this work is not executed
through the audit pipeline"*. Longer, smoother, and a claim about this plugin's role
that the operator never made.

`details.reason` is in `_journal_io.DETAILS_KEYS` precisely so the why is a structured
field rather than prose a reader must parse. That is the design saying this content is
meant to be relied on.

**Context the orchestrator wants to add goes in its own clause or its own field, never
by rewriting theirs.** And where the wording is genuinely unusable as a flag value —
empty, or it would break the shell — **ask again**. Improving it is not an option that
exists.

**A refusal from a writer script is relayed the same way: stop and relay it verbatim;
`--force --reason "<why>"` only on the human's own instruction, their words as the reason.**
No script can tell an operator's `--reason` from the model's, so this is a rule the model
follows, not one a script enforces.

## Tamper evidence and completion records

Absolute immutability of local files does not exist — the user owns the disk. The
ceiling is **tamper-evidence plus three cross-anchors**: (1) the hash-chained journal
(`scripts/governance/audit-journal.py`), (2) git history, into which the journal is staged with
every task commit (so its committed past must stay a byte-prefix of the working copy —
`verify` checks exactly that), and (3) the usage ledger, re-derivable from Claude
Code's read-only transcripts via `/audit:usage --backfill`. A forger must rewrite all
three consistently; any single-surface forgery is a `/audit:doctor` FINDING
(`check_completions` + the journal check). The journal directory must stay **tracked** —
never add it to `.gitignore`; anchor (2) only pins committed history.

The journal's **completion-record actions**:

- `task.complete` — a task's status moved to done (details: taskId, phaseId, from, to, completedAt)
- `task.blocked` — a task's status moved to blocked (details: taskId, phaseId, from, attempt =
  the task's `attempts` when it was blocked)
- `task.commit` — a task's commit moved null → SHA (details: taskId, phaseId, commit)
- `phase.signoff` — a phase reached done by its DERIVED status (details: phaseId, from, to,
  mergedAt): a stored `done`, or every task finished with a verdict recorded and, for a phase
  with a branch, the merge stamped — so the row comes from the `/audit:phase signoff` write on a
  branchless phase and from `close-phase.py`'s `mergedAt` on a branched one, and a hand-written
  `done` over a phase already done by derivation is not a second one. The verb's own row is
  `phase.verdict` (details: phaseId), the way `task.done` sits beside `task.complete`
- `ado.link` — an item's `ado.id` moved null → id, i.e. /audit:sync linked it to a
  work item (details: taskId?, phaseId, adoId). `lastSyncedAt` bumps deliberately
  draw NO row — the plan did not move (see tracker-sync.md → Journal)
- `task.move` — a task was renumbered into another phase (details: fromId, toId, fromPhase, toPhase)
- `task.block` — `audit-task.py block` set a task blocked with its reason (details: taskId,
  phaseId, reason, changes). It is the verb's own row, the way `task.done` sits beside
  `task.complete`: the hook derives `task.blocked` from a status an edit tool moved
- `task.unblock` — `audit-task.py unblock` gave a task whose attempts are spent a fresh
  budget: `attempts` back to 0 and, for a blocked task, `status` back to pending with its
  `blockedReason` cleared (details: taskId, phaseId, reason, changes)
- `task.start` — `audit-task.py start` promoted a task to in_progress (details: taskId,
  phaseId, attempt, changes; `commit` is the HEAD the start was taken at, absent outside git,
  and is where a later `done --no-change` starts the span of commits it asks about)
- `task.note` — `audit-task.py note` appended one `{at, text}` entry to a task's `notes[]`
  (details: taskId, phaseId, changes)
- `review.finding` — `audit-task.py finding` appended one finding to a phase's
  `review.findings` (details: phaseId, changes)
- `review.resolve` — `audit-task.py resolve-finding` set a finding's fix task, commit and
  resolution (details: phaseId, taskId, commit, changes)
- `review.correct` — `audit-task.py correct` rewrote a phase's `review.outcome` or `summary`
  text, never its verdict (details: phaseId, changes)
- `task.reopen` — `audit-task.py reopen` put a done task back to pending (details: taskId, phaseId,
  reason, changes - the task's cleared close and any linked bug moved back to `in_progress`)
- `plan.settle` — `audit-task.py settle` stored the derived values a plan carried stale (details:
  changes, one `{id, field, from, to}` per value: a phase's `status`, a bug's `status`/`fixedIn`).
  It is the verb's own row, the way `phase.verdict` is; the values it moves are the ones
  `validate-manifest` warned about
- `test.evidence.recorded` — a gate run was written to the evidence record (details: runId,
  taskId?, phaseId). Its subject is the **evidence file**, and it says only that a run was
  recorded — which is true the moment it is written, whatever happens to the plan afterwards
- `task.testEvidence` / `phase.testEvidence` — a `testEvidence` pointer moved (details: runId,
  taskId?, phaseId, field, from, to). Written **only after the pointer actually lands**: a pointer
  refused by another live session leaves the row above standing and no row here, because the chain
  must never assert a transition that did not happen
- `meta.evidenceSince` — the plan stated its evidence boundary for the first time, i.e. when it
  could first have recorded a run at all (details: field, from, to, runId?, phaseId?). Written by
  the recorder on the first `--record` that finds the key absent, and **only after the key actually
  lands** — a stamp a lock refused leaves no row, for the reason one bullet up. It is a row of its
  OWN rather than a detail on `test.evidence.recorded`: that row is written before the plan is
  touched and stays true whatever happens to it afterwards, so a plan-movement claim hung on it
  would assert a transition that had not happened yet and might never happen
- `audit.state.committed` — an audit-state commit was made for work no task commit will carry
  (details: commitNonce, phaseId; older rows: commit, phaseId). Written before the commit and
  carried by it, so it names the commit by the nonce its `Audit-Row` trailer carries
- `audit.index.committed`, `audit.task.committed` — the same, for a manifest-index commit and a
  task commit (details: commitNonce, phaseId, and taskId on the task row)
- `audit.commit.withdrawn` — a scoped commit whose rows were already written was NOT made (a hook
  or git refused it), so the rows keyed by this nonce name no commit (details: commitNonce,
  phaseId, taskId?, reason)
- `coupling.learned` — `audit-task.py couple` recorded (or widened) one `meta.coupling` entry
  (details: field = the coupled test path, to = its `sources` after the write, runId, commit = the
  `basis.head` the entry was learned against). A test already coupled has its `sources` UNIONED
  rather than replaced, so a widening still writes this action, once, over the same entry
- `coupling.dropped` — `audit-task.py uncouple` removed one `meta.coupling` entry by its test path
  (details: field = the test path, from = the `sources` the dropped entry carried)
- `coupling.caught` — `audit-task.py couple --test <path> --caught <runId>` set one existing
  `meta.coupling` entry's `lastCaught` from a full run that named the test failing (details:
  field = the test path, from = the `lastCaught` it replaced, null when there was none, to = the
  run row's `ts`, runId). A catch no newer than the recorded `lastCaught` writes no row, since
  nothing moved
- `bug.add` — `audit-task.py bug-add` appended one bug to `bugs[]` (details: field = the new bug
  id, to = `open`)
- `test.muted` — `audit-task.py mute` wrote or extended one `meta.muted` entry (details: field =
  the test path, from = the `until` an extended entry carried, null for a new one, to = the new
  `until`, reason)
- `test.unmuted` — `audit-task.py unmute` removed one `meta.muted` entry (details: field = the test
  path, from = the `until` the removed entry carried)
- `phase.gateDerived` — `derive-phase-gate.py` computed a phase's derived sign-off gate (details:
  phaseId, mode, changes — which of `testGateDerived`/`testGateBasis`/`testGate` this run wrote,
  `testGate` only in `enforce` mode — and basis, `phase.testGateBasis`'s own word). Written **only
  after the write lands**, the same rule every completion row here follows
- `phase.merged` — `close-phase.py` recorded that a phase reached its parent (details: phaseId,
  branch, parent; the summary says the same, `<branch> reached <parent>`). Rows written before the
  parent was kept name it in the summary only. Written **only after `phase.mergedAt` lands** - the
  stamp follows a verified containment, and a stamp that failed leaves no row - and before the
  cleanup, so a removal that fails afterwards cannot take the row with it. A re-run that finds
  `mergedAt` already recorded writes none, which is what keeps one merge to one row
- `phase.mergedHead.recorded` — `close-phase.py` added `phase.mergedHead` to a merge that was
  recorded without one (details: phaseId, field = `mergedHead`, from = null, to = the head written,
  mergedAt = the recorded moment it did not move, parent = the branch whose chain the head was read
  from, reason = the basis for the head). Which head
  depends on whether the branch still resolves. With the branch there, it is the oldest commit on
  the parent's first-parent chain that contains the tip: the commit on that chain that brought the
  tip in - the tip itself for a fast-forward, the merge commit for a direct merge, the parent's
  merge of an intermediate branch for a nested one. When the phase records task commits, that
  commit must contain every one of them, or nothing is written - a branch ref moved back onto an
  older commit fails it. `reason` then starts `recovered:` and no `mergedHeadAt` is written. With the branch gone, it is the parent's head at that moment, written only when every
  task commit the phase records is contained in it, beside `phase.mergedHeadAt` in the same write;
  `reason` names that evidence and the summary says the head is stricter than the merge commit:
  readers ask whether `mergedHead` is an ancestor of a run's head, so a run that contains the merge
  but predates this head reads provisional, never whole by accident. The evidence proves the
  parent holds the phase's recorded work, not work no task recorded; a phase recording no task
  commit fails it, and so does a parent that does not hold every recorded task commit (a rewound
  one, a squash merge, a wrong one lacking the work), and the backfill is refused
  with the reason printed - no row, and the phase stays unknown. Written **only after the head
  lands**, and never over a head already recorded. It is a row of its OWN rather than a second
  `phase.merged`: nothing merged on the run that writes it, and a reader counting merges by that
  action must not count this one

**Each action has exactly ONE writer**, and which one differs — never append any of them by hand,
because two writers means duplicate rows and a doctor that can no longer trust the count.
The `journal-writes` hook emits `manifest.edit`, `config.edit` and the four derived completion
records (`task.complete`, `task.blocked`, `task.commit`, `phase.signoff`) plus `ado.link`.
**A derived row the journal already holds is not written again.** A `git merge`, rebase or
pull moves the plan by another branch's history, and it brings that branch's journal files with
it - so a completion recorded where the work ran is found in the trail, keyed by what makes it that
completion: `task.complete` by task and `completedAt`, `task.commit` by task and SHA,
`phase.signoff` by phase and `mergedAt`. **`task.blocked` and `ado.link` are never withheld**,
because nothing in either names one record. `reopen` sets `attempts` back to 0, and a task can be
blocked again without a start in between, so neither the attempt nor `startedAt` tells two
blockings apart. A re-link to the same work item after an unlink carries the same id, and it
**is** a new `ado.link` row. A merge may therefore repeat either row: a repeated row, never a
lost one. The change itself is always recorded, and its row says how many derived rows it did
not repeat. Git's dates and the reflog's wording are never read, so a completion this call made -
whatever it then commits, rebases, cherry-picks or merges, however its commit is dated - is always
derived, and an old, unrelated completion of the same task is a different record. **Not withheld,
by design:** a sign-off of a branchless phase (`mergedAt` is null, which cannot tell one sign-off
from another), and a completion that was never recorded anywhere. Both cost a repeated row, never
a lost one.
`task.start`, `task.move`, `task.block`, `task.unblock`, `task.note`, `coupling.learned`, `coupling.dropped`, `coupling.caught`,
`bug.add`, `test.muted` and `test.unmuted` are written **in process** by `audit-task.py`, the same way its `task.done`, `task.reopen` and `plan.settle` rows
are. `phase.gateDerived` is written **in process** by `derive-phase-gate.py`, its own entry point,
for the identical reason. `phase.merged` and `phase.mergedHead.recorded` are written **in process** by
`close-phase.py`, for the same reason again: it writes the plan with `os.replace` from a script
the hook never sees, and its merges are `git` commands, not edit tools. The evidence actions are written **in process** by `_evidence_io` and
`commit-audit-state.py`, because the hook sees edit *tools* and those writers use `os.replace` and
`git commit` — the same blindness `audit-task.py` already works around.
Tokens are deliberately absent from these rows (metering lands on Stop/SessionEnd);
spend is joined from the ledger by `taskId`.

**How they come to exist, and why the tool that wrote the manifest is not part of the
answer.** The hook keeps a pre-image of each recorded path in a per-(session, target)
slot: a PreToolUse pass snapshots it before an edit-tool write, and the PostToolUse pass
diffs old against new, emits the rows above, then **refreshes the slot** to the state it
just recorded. That refresh is what makes the derivation tool-agnostic — the baseline is
the manifest as of the last journal row, so the next change is diffable whatever made it.
The PostToolUse pass therefore also runs on `Bash`, where it has no `file_path` to read
and instead compares each recorded path's digest against its slot.

Two limits are stated rather than discovered. A path with **no slot at all** has no
baseline, so that pass claims nothing and seeds one instead — a row asserting a change it
cannot see would be a claim with no basis, in the one file that exists to be trusted; the
seed is what makes the session's next write derivable. And a path that **did** move with
no parseable pre-image gets the generic row plus an explicit statement, in `details.reason`
and in the summary, that the completion records were not derived — so a gap in the trail
reads as a gap instead of as a write that moved nothing.
