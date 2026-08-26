---
description: 'Audit pipeline: execute exactly one task by id, with status guards (done/blocked/in_progress) and blocker checks. --dry-run previews without mutating.'
argument-hint: '<taskId> [--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:run — execute one task

`$ARGUMENTS` = the task id to run (plus optional `--dry-run`). Read
`${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

**If `--dry-run` is present:** follow the orchestrator's **Dry-run / preview** section — preview
whether the task is ready + what would run, and STOP without mutating.

Otherwise run the full preflight (steps 1–5, including the lock) and emit **Progress output** as you go.

Execute exactly `<taskId>`, with status guards:
1. `status == "done"` → refuse: report its `commit`/`outcome`. Offer (AskUserQuestion) an explicit
   **re-open**: on confirmation, reset `status = "pending"`, `attempts = 0`, clear `commit`,
   `outcome`, `completedAt`, `verifiedBy` — and **if `task.bugId` is set, reopen the linked bug too**
   (its `bugs[]` entry back to `status: "in_progress"`, clear `fixedIn`) so a re-opened bugfix task
   never leaves its bug marked `fixed` at a stale SHA — then execute. Never silently re-run a done task.
   A reopened task with an `ado` link gets the **ADO echo** (orchestrator.md → "ADO echo"): its card
   moves back to the pending-state with the comment `reopened by /audit:run` — the reopen was
   human-confirmed, so the board move inherits that consent.
   **`testEvidence` is deliberately not on that list.** The block is a cache of a run that
   really happened, the evidence ledger still holds that run, and `run-test-gate.py
   --reconcile` re-derives every subject's pointer from that ledger — so a cleared pointer is
   put straight back by the next reconcile or the next recorded run, and clearing it buys a
   reader nothing but a disagreement between the plan and the record, which
   `/audit:doctor` will then report. What marks the verdict as stale is the task
   reading `pending` again beside an `at` stamp older than the reopen, not a missing block.
2. `status == "blocked"` → refuse: report why (exhausted attempts / blockers). Offer a confirmed
   reset of `attempts` to 0 (back to `pending`), then execute.
3. `status == "in_progress"` → warn: likely an interrupted run — point to `/audit:resume`.
   Proceed only if the human explicitly confirms re-execution.
4. Unmet blockers → refuse and list them.
5. Otherwise run **Execute the task** (orchestrator).

Then follow **Reporting** and release the lock.

## What one run leaves behind

**The gate run that becomes evidence is yours, not the subagent's.** The orchestrator's
*Execute the task* holds the invocation and the reason; what matters here is that the
subagent's own run is what it develops against, and the recorded one has to be the
wrapper's — the bracket, the check count, the coverage answer and the tree comparison are
only true of a run the wrapper made. `--record` prints two lines: one says the row was
written, the other whether the plan now names it. Read both. A **refused pointer is not a
failure** — another live session may hold the phase lock — so do not retry the gate to
chase one; the row stands either way and `--reconcile` catches the plan up later.

A step that outruns `--timeout` (the script's own default when nothing passes one) is torn
down and recorded as having timed out, and the tree comparison is then **refused rather than
guessed**: a descendant that escaped the kill is still writing, so comparing the snapshots
would be a race whose answer changes with timing.

**A single-task run is the case where a failed gate has nothing to ride out on.** A task
commit stages the evidence directory, so inside a phase run an attempt that failed and was
retried is made durable by whatever commits next. This command commits only when the task
reaches `done` — so when it ends `blocked` with its attempts exhausted, and on the
infrastructure path that stops without committing, the rows just written sit in the working
tree with nothing coming behind them. Both are named points in the orchestrator's
*Keeping a failed run's record*; run
`commit-audit-state.py` at them. It stages the phase's manifest file, the journal and the
evidence directory and **never the task's `files`** — the implementation stays unstaged,
which is what makes committing a failed task's state possible at all.
