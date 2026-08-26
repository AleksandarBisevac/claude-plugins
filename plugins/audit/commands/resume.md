---
description: 'Audit pipeline: resume an interrupted run — find the in-progress phase and continue from the first uncommitted task.'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:resume — continue an interrupted run

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run the full preflight
(steps 1–5, including the lock) and emit **Progress output** (orchestrator) as you go.

Run the **Resume after interruption** procedure (orchestrator): find the in-progress phase and its
branch, compare committed work, and continue from the first task whose `commit` is null/missing.
Use after a crash, a lost session, or any interrupted `/audit:phase` / `/audit:next` / `/audit:run`
(`/audit:status` flags when a phase is resumable). Then follow **Reporting** and release the lock.

## Sweep the interrupted session's record first

Once the in-progress phase is identified and before continuing from the resume point, run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-audit-state.py" <manifestPath> <phaseId>
```

**This is the point the record of an interrupted run depends on.** A gate that was torn down
records its row and returns — git belongs to the orchestrator, and a commit made while
stopping is how a half-made one happens — so what a lost session leaves behind is a row in
the working tree that nothing is going to carry. A task commit would have carried it; an
interrupted run never reached one. This is that sweep, and it is the resume entry among the
points the orchestrator's *Keeping a failed run's record* names.

**It stages the phase's manifest file, the journal and the evidence directory, and never the
task's `files`** — which is exactly what makes it safe to run here. The interrupted task's
working-tree changes are the thing the orchestrator's own resume step calls **untrusted**
and refuses to discard without confirmation; this commit must not settle that question in
the other direction by sweeping them into git on its way past. The
exclusion is enforced rather than intended: paths are staged by name, the index is read back
and compared against the same allow-list before anything is committed, and
`verify-invariants.py`'s `audit-state-scope` re-derives the rule from git afterwards.

**Calling it when nothing is wrong costs a line of output.** With nothing uncommitted it
makes no commit and says which do-nothing state it was in — including the one where the only
uncommitted thing is a journal row, which rides along with the next commit rather than
earning one of its own. So run it on every resume rather than first deciding whether this
particular interruption left anything; deciding is what it is for.
