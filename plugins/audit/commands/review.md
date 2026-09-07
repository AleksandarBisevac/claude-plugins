---
description: 'Audit pipeline: re-run Phase sign-off for a phase on demand (e.g. after fixes) — review, test gate, invariant check, optional runtime boot, merge.'
argument-hint: '<phaseId>'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:review — re-run a phase's sign-off

`$ARGUMENTS` = the phase id. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run the full preflight
(steps 1–5, including the lock) and emit **Progress output** (orchestrator) as you go.

Run **Phase sign-off** (orchestrator) for `<phaseId>` — use when tasks are already `done` and you
want to re-run the review / test gate / invariant check / runtime boot / merge (e.g. after applying
fixes). Then follow **Reporting** and release the lock.

**The invariant check (sign-off step 3) reads the phase BRANCH.** Re-running sign-off after the
branch was deleted is legitimate, and `verify-invariants.py` will answer `no-basis` for
`branch-history` rather than `clean` — read that as "the evidence is gone", not as a problem with
this run. `meta.merge.deleteBranch` is on by default, so on a phase that already landed this is
the **normal** outcome of a re-run, not a sign that something went wrong.

**Re-running the landing step is safe and says so.** `close-phase.py` asks the ancestry before it
writes anything, so a phase whose branch is already contained in its parent reports
`already-contained`, makes no git write at all, and exits 0. What a re-run WILL still do is the
cleanup the first run could not — a worktree that was dirty then and is clean now, or one the
first run was standing inside. Its `--dry-run` shows exactly that before you commit to it.

The reviewer is **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** — the
first level that is **present** answers, an explicit `null` **is** an answer (skip review; tests are
the signer), and with several `area` tags written order decides. `/audit:status --phase <phaseId>`
prints the resolved skill and the basis it came from; read that rather than re-deriving it.
