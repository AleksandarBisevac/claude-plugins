---
description: 'Audit pipeline: everything a phase has done to it — run it end to end (every ready task, parallel where safe, then sign-off), pin which phase the pipeline reaches for first, or cancel one that will not be done. A bare `<phaseId>` runs it; --dry-run previews the run without mutating.'
argument-hint: '<phaseId> [--dry-run] | priority <phaseId> <tier> [--force] | priority <phaseId> --clear | cancel <phaseId> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:phase — run a phase, order it, or close it

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

## 0. Which verb — read off `$ARGUMENTS`, before the manifest is

The FIRST token decides, and only two words are reserved: `priority` and `cancel`.
**Any other first token is a phase id**, and the command is the run form below — the
shape this command has always had, unchanged.

**Lexical, never inferred from the plan.** Deciding the verb by asking the manifest
whether the first token happens to name a phase would give one command line two
meanings on two machines, and the argument has to be read before the manifest is even
located. So the rule is about the word, and it is the same word everywhere.

**The one collision, and it is asked rather than guessed.** `phase.id` is a free-text
string in `${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json` — `P<n>` / `BF<n>` is
the allocation convention (conventions → ID allocation), not a shape the validator
holds — so a hand-written manifest MAY carry a phase whose id is one of the reserved
words. Once the manifest is read, if it names a phase whose id equals the word you
dispatched on, **STOP**: print both readings and ask (AskUserQuestion) which was meant,
then follow the answer. Never resolve it silently and never refuse outright — both
readings stay reachable, one question apart. There is no arity exception either: three
tokens are no more decidable than one when a rule has a carve-out nobody remembers.

## Run a phase — `<phaseId> [--dry-run]`

`$ARGUMENTS` = the phase id (plus optional `--dry-run`).

**If `--dry-run` is present:** follow the orchestrator's **Dry-run / preview** section instead —
read-only preflight, print the plan (branch, ready tasks, parallel groups, merge target), and STOP.
The branch and the merge target both come from
`resolve-branch.py <manifestPath> --phase <phaseId>` — never composed here — and when the
merge target is not `meta.developmentBranch`, the plan says so: signing off there does not put
the work on the development branch.

Otherwise run the full preflight (steps 1–5, including the lock) and emit **Progress output** as you go:

0. **Print the scoped entry view first, verbatim:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --phase <phaseId>` —
   the phase's tasks, their statuses, what each is waiting on, and the whole-plan totals.
   Deterministic, so it costs nothing to lay out. The per-task **Progress output** lines below
   are yours to emit as the work happens; only this entry view is pre-rendered.
1. If the phase is `done` → refuse; point to `/audit:review <phaseId>` to re-run sign-off.
2. Execute every **ready** task in the phase in parallel where safe (disjoint `files` and satisfied
   `dependsOn`), sequentially otherwise. (**Execute the task** performs phase entry — branch,
   `baseRef`, phase status — on its first run.)
3. Re-evaluate readiness and repeat until no task in the phase is ready.
4. When **all** tasks in the phase are `done`, run **Phase sign-off** (orchestrator).

Then follow **Reporting** and release the lock.

## Subcommand: `priority <phaseId> <tier>` (or `priority <phaseId> --clear`)

Say which phase the pipeline should reach for first. Until this verb the order was implicit
in the array — `phases[]` as written, then task id inside a phase — so "run this one next"
meant physically moving the phase, a structural edit of the whole file that nobody performs
in flight.

**It re-sorts only work that is ALREADY ready.** A priority never makes an unready task ready
and never skips a dependency: a pinned phase still waiting on its `blockedBy` is skipped, and
`/audit:status` prints the note saying so and naming the task that ran instead. It is a wish
about the schedule, not a permission.

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST and resolve the manifest.
This is a SCRIPT call — it takes the index lock itself, so hold no lock by hand around it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/set-priority.py" \
  <manifestPath> P5 1 [--force] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/set-priority.py" \
  <manifestPath> P5 --clear
```

- **Tier 1 is unique**; 2, 3, 4 … are shared. Without `--force` a second holder of tier 1 is
  refused and the refusal **names the phase that already has it** — relay that name, and offer
  clearing it or picking another tier before reaching for `--force`. With `--force` both are
  written and the one that comes FIRST in the manifest wins; the validator says so as a warning.
- **No priority at all means unprioritised** — the phase sorts after every pinned one and keeps
  its written position among its peers. Clearing a pin is `--clear`, which removes the key; there
  is no "priority 0".
- **`priority.maxTier`** in `.claude/audit.config.json` is advisory. A phase pinned above it keeps
  the tier it was given and simply sorts after every tier at or under the maximum — nothing is
  clamped, and the command says so.
- The value lives on the **index stub** in the sharded layout, so one file is written and a phase
  run editing its own shard cannot collide with it.

**Exit codes:** `0` written (or already that value — it says so and writes nothing). `1` the
manifest was already invalid, or the write would have left it invalid and was rolled back.
`2` unknown phase, a tier that is not a positive integer, or a second holder of tier 1 without
`--force`. `3` the index lock is held by a live run — stop; do not take it over. `4` the lock
looks abandoned — confirm with the human (AskUserQuestion), then re-run with `--takeover`.

**Display order does not change.** `/audit:status`, both reports and the panel keep showing the
plan in the order it was written — the written plan IS the plan. The pin shows as a badge on the
phase row and decides which READY task comes first.

**`/audit:task priority <phaseId> <tier|--clear>` is the legacy spelling** and still does exactly
this. It is documented in `${CLAUDE_PLUGIN_ROOT}/commands/task.md`; new work says
`/audit:phase priority`, because the field is `phase.priority` and no task has one.

## Subcommand: `cancel <phaseId> --reason "<why>"`

Close a phase that will **not** be done — the feature was dropped, the approach was
abandoned, the phase ends with whatever landed. Not failure and not `done`: `cancelled`
is the second TERMINAL state, and the report files it under **Archived** beside the
finished work.

**The procedure is `${CLAUDE_PLUGIN_ROOT}/commands/task.md` → *Subcommand: `cancel`*.**
Read it and follow it with the id fixed to a phase id. There is no second copy of it here
on purpose: one writer means one description of what it writes, what it refuses and what
it rolls back, and two copies of that is one copy and one lie. The cascade to the work
still open inside the phase, the released claim and the journal row are all stated there.

**What this spelling adds is a narrowing.** `<phaseId>` must resolve to a **phase**. An id
that resolves to a task → **refuse before any write**, and name the spelling that takes
one: `/audit:task cancel <taskId> --reason "<why>"`. A command called `phase` mutating a
task is the same noun/verb mismatch this spelling exists to remove, so it is refused
rather than accepted quietly.

**`/audit:task cancel <phaseId>` still does exactly this** — the legacy spelling for a
phase, kept so existing transcripts and runbooks resolve. New work says
`/audit:phase cancel`.
