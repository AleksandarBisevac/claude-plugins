---
description: 'Audit pipeline: re-run Phase sign-off for a phase on demand (e.g. after fixes) — review, test gate, invariant check, optional runtime boot, merge.'
argument-hint: '<phaseId> [--full]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:review — re-run a phase's sign-off

`$ARGUMENTS` = the phase id. Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md`,
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/phase-signoff.md` first — this command re-runs sign-off and
never executes a task on its own account, so it does not read `reference/execute-task.md`. Run
the full preflight (steps 1–5, including the lock) and emit **Progress output** (orchestrator)
as you go.

Run **Phase sign-off** (orchestrator) for `<phaseId>` — use when tasks are already `done` and you
want to re-run the review / test gate / invariant check / runtime boot / merge (e.g. after applying
fixes). Then follow **Reporting** and release the lock.

**Every actionable finding gets a NEW TASK, and this command creates and starts it — you do not
hand the operator a command to run.** Sign-off runs when every task is `done`, and the plan gate opens a
file only through a task that is **running**, so a fix run spawned straight off a finding is refused
on the first file it edits. For each finding, before spawning anything:

```
/audit:task add "<the finding>" --phase <phaseId> --files <the files it touches>
/audit:run <the id that add printed>
```

`add` works while the phase is in sign-off; it lands `pending` and prints `ready now -- /audit:run
<id>`. It applies to a finding whose file a task already declares just as much as to one in an
undeclared file — the declaration is not what opens the file, the running task is. **`/audit:task
scope` is not a substitute**: it accepts a widening on a `done` task and says so, and a `done` task
opens nothing.

Record each finding in `phase.review.findings` in the shape the schema names — `id`, `severity`
(`low`, `med` or `high`), `file`, `issue`, `resolution`. `validate-manifest.py` warns on a finding
missing a field or carrying a severity outside that vocabulary; a free-text finding records nothing
a later run or a report can read back.

**The invariant check (sign-off step 3) reads the phase BRANCH.** Re-running sign-off after the
branch was deleted is legitimate, and `verify-invariants.py` will answer `no-basis` for
`branch-history` rather than `clean` — read that as "the evidence is gone", not as a problem with
this run. `meta.merge.deleteBranch` is on by default, so on a phase that already landed this is
the **normal** outcome of a re-run, not a sign that something went wrong.

**Re-running the landing step is safe and says so.** `close-phase.py` asks the ancestry before it
writes anything, so a phase whose branch is already contained in its parent reports
`already-contained`, makes no merge write, and exits 0 - keeping the `mergedAt` it recorded
rather than moving it. A phase that landed and whose branch is already gone reports that and exits
0 too. The sign-off it judges the cleanup by is the phase as the BRANCH holds it, so a phase
signed off in its worktree lands and is cleaned up in one run from the parent's tree. What a re-run WILL still do is the
cleanup the first run could not — a worktree that was dirty then and is clean now, or one the
first run was standing inside. Its `--dry-run` shows exactly that before you commit to it.

**The landing commits the stamp it writes.** `mergedAt` and the stored `done` go into the
parent's copy of the plan, and `close-phase.py` commits them there through
`commit-audit-state.py` (and `commit-manifest-index.py` in a sharded plan), subject `landed on
<parent>`. With the parent checked out nowhere and the main tree on the phase branch, the commit
goes on that branch and the parent is fast-forwarded to it once more. A re-run commits a stamp an
earlier landing left uncommitted, and makes no commit when there is none.
The `landing-committed` invariant - in `verify-invariants.py` and `/audit:status --gate` alike -
reports a landed phase whose stamp is still
an edit in the tree it runs in.

**Under the step driver, sign-off is one step.** `drive-phase.py next <phaseId>` prints the phase
reviewer's dispatch once every task is closed, records the filed review's findings in one
`finding` call, and prints one `decide triage`; answered `sign-off` with the summary, it runs the
phase gate, the invariants check, the sign-off verb, the commit, the landing and the lock release,
and stops before the sign-off verb when the phase gate is red.

The reviewer is **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** — the
first level that is **present** answers, an explicit `null` **is** an answer (skip review; tests are
the signer), and with several `area` tags written order decides. `/audit:status --phase <phaseId>`
prints the resolved skill and the basis it came from; read that rather than re-deriving it.

**`--full`** runs the third place after the ordinary sign-off completes, through its one command:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/full-gate.py" <manifest> [--project-dir <dir>]`
— the same command the README's pre-push snippet runs. It runs `run-test-gate.py <manifest>
--full --record` as a subprocess, measured against the whole product rather than this one phase,
streams what the runner prints and exits with the runner's code. Neither script prints the
phase's full-run answer; read it afterwards where it is printed — `/audit:status`'s tests column
(`full whole`, `full provisional (since …)`, `full unknown - <reason>`) and `/audit:doctor`'s
`full run` row (a WARNING naming a PROVISIONAL or UNKNOWN phase with its basis, one OK row when
every merged phase reads WHOLE), both off `_evidence_io.full_status`. `/audit:status` asks git
from `CLAUDE_PROJECT_DIR`, or the directory it runs in when that is unset, so run it from the
project's own checkout. A plan with no
`meta.fullGate` declared prints that the plan names no third place and exits 0; that is not a
failure of this command, it is the plan's own state.

**A red `--full` files what the run taught, and stays red.** After the runner exits non-zero,
`full-gate.py` reads the row it recorded and runs `audit-task.py` itself: a `couple` and a
`bug-add` for each selection miss the runner named, and a `couple --caught` for each coupled suite
it named failing and did not list as a miss (orchestrator → **What a red full run teaches**). Each verb's own lines and exit
code are printed under `[full-gate]`, and so is every reason nothing was learned. The exit is
still the runner's, and the phase's full-run answer is still the one the ledger holds; a filed
miss does not make the red run anything but red. Report the coupling and the bug it filed with
the rest of the sign-off.
