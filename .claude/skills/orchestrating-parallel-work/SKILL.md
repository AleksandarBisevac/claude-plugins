---
name: orchestrating-parallel-work
description: How to run several subagents against one repository without losing their work or misreporting it — taking a worktree's diff against the base that worktree actually had, closing a task with the verb instead of hand-editing two files, never reaching for a tree-wide destructive git command, and checking a claim about work in flight before saying it out loud. Use this skill whenever you are about to spawn subagents in worktrees, take work back out of one, say what an agent is doing or has done, mark a task or phase finished, clean up after a failed apply, or write a brief that tells an agent what the code holds. It applies to the ordinary hand-off, not only the messy one: every failure it guards against was made by an orchestrator who knew the rule and did not check at the moment.
---

# Orchestrating parallel work

Running several agents against one repository is mostly bookkeeping, and the bookkeeping
fails in a small number of ways that all look like carelessness and are not. Each rule
below was written after the failure happened here, in a run where the orchestrator knew
the rule already. Knowing is not the problem. The moment of action is.

So every rule names the command that checks it. A rule you cannot check at the moment you
act is a rule you will follow when you are calm and skip when you are three agents deep.

## Before you say what an agent is doing

**A claim about work in flight is checked before it is spoken.** `ListAgents` says what is
running; `git status` in the worktree says what has been written. Both are cheap.

This exists because an orchestrator here reported a task as running when no agent had been
spawned for it — the task and its worktree had been created, the launch was intended, and
the intention got written down as a fact. The worktree was clean and the agent list was
empty; either check would have caught it in seconds.

The transcript size is not the signal. It does not grow while an agent works. The worktree
does.

## Taking work out of a worktree

**Use `tools/harvest-worktree.py <worktree>`, which is what enforces every rule in this
section** — it derives the base, refuses when the base is not derivable, and prints the
report the rest of this section asks you to read:

```bash
python3 tools/harvest-worktree.py <worktree> --out <patch>   # 0 harvested, 3 no work,
                                                             # 1 refused, 2 usage
```

**Never a branch name**, because the branch has moved since the agent started. An
orchestrator here took `git diff main` from a worktree whose `main` had advanced, and
applying that patch silently reverted a sibling task's test cases. Nothing failed. It was
caught because a case count dropped, and only because someone looked.

**And not its own HEAD either, whenever the agent committed** — this section used to say
HEAD and that is right only for a worktree that left everything uncommitted. An agent that
committed has moved HEAD past its own base, so `git diff HEAD` shows the dirty tree alone
and silently drops every committed change. The base is the commit the worktree *started*
at, which the tool reads out of that worktree's own HEAD reflog; hand-composing it is where
both mistakes live.

**Read the whole report, never its last line.** The same orchestrator read the last line of
a multi-file `git apply` and concluded the patch had landed when most of it had not. The
report names every file with its own counts, every commit on top of the base, and whether
the tree is dirty — which is what tells "the agent wrote nothing" from "the agent committed
and the tree is clean", two states a `git status` renders identically.

**A refusal is a finding, not an obstacle.** Exit 1 means the base is not knowable — the
worktree was rebased off its base, its reflog was expired, or you pointed at the main
worktree — and the fix is to establish which commit the work sits on and pass `--base
<rev>`, never to fall back to a branch name.

**After applying, run the suites the patch touched and compare the case counts with what
the agent reported.** A count that dropped means the patch reverted something. That
comparison is the whole check; a clean `git apply` proves only that the hunks matched, and
the tool deliberately does not apply so that this step belongs to the process that can
watch it.

## When an apply goes wrong

**Undo by naming paths, never by resetting the tree.**

```bash
git checkout -- <the paths you applied>     # yes
git reset --hard                            # no
```

`reset --hard` here destroyed three things at once that had nothing to do with the bad
apply: a skill revision that was waiting to be committed, the manifest index, and a
phase's completion marks that existed in no other file. All of it was recoverable only
because the commits happened to carry the same facts in their subjects.

The general shape: a destructive command scoped to the tree takes everything uncommitted
with it, and what is uncommitted is by definition the work you have not yet proven. If a
guard refuses one of these, read what it says was at risk rather than reaching for a
bigger hammer.

**Commit as soon as a piece is verified.** Work that is finished and uncommitted is work
one careless command away from gone. This is not tidiness; it is the only thing that made
the loss above recoverable.

## State that lives in two places lives in neither

**Use the verb. Never hand-edit the same fact into two files.**

The completion marks lost above had been hand-written into a phase shard and an index.
When the index was reverted, the shard turned out never to have carried them — so the
record of finished work survived only in commit subjects. A verb writes one record, under
the lock, with a journal row, and cannot write half of it.

If there is no verb for what you are doing, that absence is the finding. Say so and record
it; do not quietly hand-edit around it. A missing verb is exactly why the hand edit felt
necessary, and the next orchestrator will feel the same way.

## Writing a brief

**A brief is a claim surface, so it answers the same questions a comment does.** Read
`before-you-claim` — in particular, whatever you tell an agent about what the code holds
is a claim about behaviour, and it is checked the same way: name the file and line, or do
not assert it.

An orchestrator here told an agent that an evidence row carried a field, because a task
that would have added it had been planned. It had never been created. The agent read the
code, found the field absent, and wrote what the record could actually support — but an
agent that trusted the brief would have documented a mechanism that does not exist, and
the brief would have been the source.

**Give the agent the failure, not just the goal.** A brief that carries what was driven —
the payload, the verdict, the line number — produces work you can check. A brief that
carries only an instruction produces work you have to re-derive.

**Name the allow case.** For anything that refuses, says no, or filters, the brief should
name what must stay quiet as explicitly as what must be caught. Agents reliably build the
deny half and leave the allow half to luck, and the allow half is what decides whether the
thing survives its first week.

## Judging what comes back

**The agent locates and implements; the verdict is yours, and it comes from running.** A
report that a suite is green is a claim about a suite. Run the thing the change is about,
in the shape the field reported it, and compare.

Expect your own probe to be wrong before the code is. In one run here three probes were
wrong in a row — a fixture that could not reach the branch under test, a shape that
collapsed two cases into one, an argument that silenced the output being measured. Each
time the first instinct was that the implementation had failed. If a probe reports
something surprising, suspect the probe first; it is newer than the code.

**A mutation that survives is information, not a nuisance.** It usually means the case is
asserting something other than what it claims, or that another condition already covers
the one you are testing. Both are worth knowing before the work is trusted.

## Keeping the queue full

**Report alongside the work, never instead of it.** A finished phase is a moment to start
the next one, not to stop and write. An orchestrator here treated "report at the boundary"
as "pause at the boundary" and left both slots idle while composing a summary.

**Fill the freed slot before doing anything else with a result.** Applying, verifying and
committing a returned patch takes several minutes; a slot left empty for those minutes is
time nothing is being built.

## The shape of a good hand-off

One task, one worktree, one brief that carries the driven evidence, the allow case named,
and the verification commands stated with the exit codes you expect. Then: harvest with
`tools/harvest-worktree.py`, read the report rather than a line of it, apply, run the
suites, compare the counts, drive the behaviour yourself, commit while it is fresh.
