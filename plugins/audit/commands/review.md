---
description: 'Audit pipeline: re-run Phase sign-off for a phase on demand (e.g. after fixes) — review, test gate, optional runtime boot, merge.'
argument-hint: '<phaseId>'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:review — re-run a phase's sign-off

`$ARGUMENTS` = the phase id. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run the full preflight
(steps 1–5, including the lock) and emit **Progress output** (orchestrator) as you go.

Run **Phase sign-off** (orchestrator) for `<phaseId>` — use when tasks are already `done` and you
want to re-run the review / test gate / runtime boot / merge (e.g. after applying fixes). Then
follow **Reporting** and release the lock.

The reviewer is **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** — the
first level that is **present** answers, an explicit `null` **is** an answer (skip review; tests are
the signer), and with several `area` tags written order decides. `/audit:status --phase <phaseId>`
prints the resolved skill and the basis it came from; read that rather than re-deriving it.
