---
description: 'Audit pipeline: everything a phase has done to it — add one to a plan that already exists, run it end to end (every ready task, parallel where safe, then sign-off), pin which phase the pipeline reaches for first, or cancel one that will not be done. A bare `<phaseId>` runs it; --dry-run previews the run without mutating.'
argument-hint: '<phaseId> [--dry-run] | add "<title>" --outcome "<what success is>" [--gate <entry>] [--gate-clear] | retarget <phaseId> [--gate <entry>] [--gate-clear] [--area a,b] [--outcome TEXT] | priority <phaseId> <tier> [--force] | priority <phaseId> --clear | cancel <phaseId> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:phase — add a phase, run it, order it, or close it

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

## 0. Which verb — read off `$ARGUMENTS`, before the manifest is

The FIRST token decides, and the reserved words are `add`, `retarget`, `priority` and `cancel`.
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

## Subcommand: `add "<title>" --outcome "<what success looks like>"`

One more phase in a plan that already exists. Until this verb nothing in the tree
appended to `phases[]` except the ADO pull: `/audit:init` synthesizes a WHOLE plan,
`/audit:propose materialize` MOVES a payload that was parked earlier, and
`/audit:task add` needs the phase to be there already. So a maintainer whose plan
had outlived its first round — the state every long-lived plan ends in — could
re-run init over finished work, pull from a board, or hand-edit the index and write
a shard. All three are wrong, and the third is wrong twice in the sharded layout,
where a new phase means a new shard file **and** an index stub pointing at it.

This is a SCRIPT call — it takes the index lock itself, so hold no lock by hand
around it. Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` → *New
phase template* first; the script IS that template, and hand-writing the fields is
the class of error it exists to delete.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" add-phase "<title>" \
        --outcome "<what success looks like>" \
        [--id P7] [--description "<why & how>"] [--area a,b] \
        [--gate "<entry>" ...] [--blocked-by id,id] [--review-skill NAME] [--json]
```

**Print the script's output verbatim — validator warnings included.** It names the id,
the outcome, the gate and where it came from, and the files it wrote.

**What you gather before running it** (ask only for what `$ARGUMENTS` does not carry):

- **`--outcome` is required, and it is the one question worth insisting on.** It is
  the one-line `desiredOutcome`: `/audit:status` shows it, task subagents receive it,
  and Phase sign-off must address it. A phase whose success cannot be stated in a
  line is already too big — that is the conventions' own splitting rule, and this is
  where it gets applied. The script refuses a blank one.
- **`--id`** — omit it. The script continues the `P<n>` sequence over live phases AND
  every id a parked `proposals[].payload` reserves (conventions → ID allocation), which
  is the same allocation `/audit:propose materialize` uses. Pass it only when the human
  named an id, and relay the refusal if it collides.
- **`--gate`** — repeatable. Omitted, the gate comes from `meta.buildCommands` keys.
  The report says which of the two happened, and says so when the gate is EMPTY: a
  phase with no gate is signed off on review alone, which is a decision rather than a
  detail.
- **`--area`** — the area tag(s) whose `root` the phase's work falls under. One tag is
  written as a string, several as a list, in the order you want them to resolve.
- **`--description`**, **`--blocked-by`**, **`--review-skill`** — optional.

**Before creating one, check the alternatives** and say which you ruled out:

- a still-parked proposal (`proposals[]`, status `proposed`) already covering this
  work → `/audit:propose materialize <PROP-id>` is a MOVE and keeps the reservation
  honest, where a parallel hand-made phase would duplicate it;
- an open phase whose `desiredOutcome` this work already serves → `/audit:task add
  --phase <id>` instead. Two phases whose gate and outcome are indistinguishable are
  one phase.

**What it writes**: the phase, template-initialized exactly once — `status: "pending"`,
`baseRef`/`branch`/`mergedAt`/`summary` null, the `review` object, an empty `tasks` —
**appended last**, because the written order is the plan's order and `/audit:phase
priority` is what says "reach for this one first". In the **sharded** layout it writes
the phase's new shard and adds the index stub that points at it, and touches no other
shard. Then it re-reads the manifest from disk, revalidates, and **rolls every written
file back byte-for-byte** on findings — including deleting a shard it had just created,
so a refusal never leaves a phase body the index does not point at. Finally it appends
a `phase.add` journal row carrying the outcome.

**Refusals, all before any write:** a missing or blank `--outcome`; an `--id` that is
already a live phase (it says so, and offers `/audit:task add --phase <id>` when that
phase is still open); an `--id` a parked proposal reserves (it names the proposal and
points at `/audit:propose materialize`); an `--id` that is already a task id; and — in
the sharded layout — an `--id` whose shard FILENAME an existing phase already occupies,
because two ids the filename cannot tell apart would overwrite one another.

**Exit codes:** `0` written. `1` the manifest was already invalid (nothing written), or
the phase would have left it invalid and every written file was rolled back. `2` usage —
the refusals above. `3` the index lock is held by a live run — stop; do not take it over.
`4` the lock looks abandoned — confirm with the human (AskUserQuestion), then re-run with
`--takeover`.

**Then hand off**: `/audit:task add "<the first task>" --phase <newId>`, which the report
already prints, and `/audit:status` to see the phase in the plan.

## Subcommand: `retarget <phaseId>`

Correct a phase that already exists: `--gate <entry>` (repeatable) or `--gate-clear`,
`--area a,b`, `--outcome TEXT`, `--description TEXT`. Runs
`scripts/manifest/audit-task.py retarget` — same lock, same revalidate-or-roll-back,
same journal shape as `add`.

**Why a verb and not a flag on `add`.** The values already exist and are wrong.
`/audit:init` and `/audit:sync pull sprint` synthesize a phase and choose its
`testGate`; from that moment the choice was unreachable, and one wrong choice is enough
to make a phase unable to pass its own sign-off. Measured: an imported phase was given
`testGate: ["lint"]` because a build key existed, `lint` on that repo runs a Python
pre-commit suite, and the phase's tasks touched only JSON and Markdown. Every route out
was outside the plugin — a hand edit the plugin forbids, a `buildCommands` value that is
a shell hack, or installing a third-party tool to satisfy a gate the plugin itself
picked.

**`--gate-clear` is the point, not a convenience.** `--gate` appends, so without an
explicit clear there is no spelling for the EMPTY gate — and the empty gate is a
designed state, not a hole: `audit-task.py:_phase_gate` returns it with a basis, and its
docstring says why it needs one, because *a phase nothing can prove done is a phase
sign-off signs on review alone*. `/audit:phase add --gate` could already reach it for a
NEW phase. An imported one could not, which is what turned a guessed gate into a trap.
The report says so when the gate ends up empty, rather than leaving silence to be read
as breakage.

**Not a done or cancelled phase.** Its sign-off was given against the gate it had, and
moving that afterwards rewrites what the sign-off attested. A phase that is `pending` or
`in_progress` is exactly the case this verb is for.

`--gate` and `--gate-clear` together are refused: two answers about one field, and
guessing which was meant is the fault this closes. `--area` with an empty value REMOVES
the key rather than writing `null`, because the conventions default it to absent and a
`null` would make an untagged phase claim to have considered the question.

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

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.

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
