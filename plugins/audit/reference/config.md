# Configuration keys read by the step driver

`README.md`'s Configuration table states every key in one row; this page holds
the detail for the keys whose behaviour needs more than a row.

## `ci.cadence` — CI before landing

A phase that runs for days used to meet CI only when it landed, so a regression
it introduced on another platform surfaced after the work on top of it was
done. `ci.cadence` asks earlier.

```json
{ "ci": { "cadence": { "closes": 3, "hours": 6 }, "workflow": "ci.yml" } }
```

- `closes` — dispatch at every N-th task close since the last dispatch.
- `hours` — dispatch at the first close after H hours of phase time since the
  last dispatch (the phase's `startedAt` before the first one).
- Name one or both; either is enough. Neither, a `closes` below 1 or an `hours`
  at or below 0 is **refused** (`/audit:doctor` and the validator name it), never
  read as "landing only".
- `ci.cadence` absent: the driver makes no CI call at all, as before the key
  existed.

What the driver does, at a close that makes a dispatch due:

1. pushes the phase tip to `ci/<phase id, lower-cased>` (`git push origin
   +<sha>:refs/heads/ci/<phase>`; the branch is a throwaway the driver owns);
2. dispatches `ci.workflow` on that branch (`gh workflow run <workflow> --ref
   ci/<phase>`) and **does not wait** — the drive goes on to the next task;
3. at the **next close**, and when sign-off begins so a verdict after the last
   close is not dropped, finds the run for that commit (`gh run list`, one
   call). A completed run is handed to `full-gate.py --ci-run <run> --phase
   <P>`, the one path from CI to the plan, which reads it (`gh run view`) and
   records it on the phase as `ci` - `runId`, `sha` (the head the run graded),
   `conclusion` and `at`:
   - `failure`, `timed_out` or `startup_failure`: it also files one `high` bug
     naming the branch, the commit, the run, its URL and its failed jobs, so
     the release guard and the open-bug rule see it at once;
   - any other conclusion: recorded, no bug;
   - the failed jobs are read in a second call, for a red run only: a `gh`
     that cannot list them still has the run recorded, and the bug says the
     failed jobs could not be read, in `gh`'s words;
   - the same run read again: nothing is written and no second bug is filed;
   - still running, not listed yet, a list that cannot be read, or a run whose
     id, head, status or conclusion cannot be read (`full-gate.py` exits 6):
     said in the did-line, nothing recorded, the run read again at the next
     close, and nothing new is dispatched on top of it.
4. just before the sign-off commit it reads a run still held once more, and
   every outcome leaves a record, so the commit says what CI had said by then:
   - concluded: recorded as above;
   - still running: recorded with its run id, a `basis` naming its status and
     no `conclusion`;
   - not listed yet, or a list that cannot be read (no `gh`, no credentials):
     recorded through `full-gate.py --ci-unreported` with the head and a basis
     naming the workflow, the branch and, for an unread list, `gh`'s words;
   - listed but not readable: recorded the same way with the run's id
     (`--run`) and a basis saying which read failed, in `gh`'s words.
   The sign-off goes on in every one of these. It stops only when the record
   itself is refused (the plan would not validate with it), on a usage error,
   or on the plan lock; the stop prints `full-gate.py`'s words, which name the
   repair or the rerun, then that the next `next` reads the run again and that
   taking `ci.cadence` out of the config goes on without CI.

After the sign-off commit nothing reads CI again: a run that ends red after
it, or one whose word could not be read at it, stays in the plan as a record
with a basis and files no bug.

A push or dispatch that fails (no remote, no `gh`, no credentials) is said in
the did-line and tried again at the next close. The driver never prompts for
credentials and never reads stdin on these calls.

## `usage.ledgerDir` — the record a commit's co-author trailer is read from

The commits the driver makes through `commit-task-work.py` follow one trailer
rule, and it reads the usage ledger the metering hook writes under this key
(default `.claude/usage`), through the same `hooks/_config.ledger_dir` the
writer uses:

- **A task commit**, on a plan whose `meta.commit.coauthor` is set, carries one
  `Co-Authored-By: <model id> <noreply@anthropic.com>` line per model the
  ledger recorded as the task's executor since its start - rows labelled with
  the task from the executor's own Agent description, by the plugin's executor
  agent. Nothing recorded is no trailer, said on a `degraded:` line; the
  plan's line itself is never written. `meta.commit.coauthor` unset is no
  trailer, as it always was.
- **The driver's own state commits** - `--state` after a block, at sign-off and
  at a landing - carry **no** co-author trailer, whatever the plan says: they
  hold the plan's record, which the plugin's verbs wrote, and no model's work.

`usage.enabled: false` writes no ledger rows, so a task started while it is off
commits with no trailer.

## `journal.enabled` — which rows the trail holds

One key, three values, and the default is the middle one:

| Value | The verbs' own rows | Each Edit, Write and Bash call |
|---|---|---|
| unset (default) | written | not recorded: no row, no pre-image file |
| `true` | written | recorded, as every release before 4.0.0 did unset |
| `false` | not written | not recorded |

The verbs' own rows are what the driver reads: a task's start, a close, a bug
filed, and the row whose nonce a task commit's `Audit-Row` trailer carries - how
`drive-phase.py` finds a commit it already made of a task. They are written
whenever the key is not `false` (`_journal_io.enabled`). The per-call rows are
`journal-writes.py`'s: a `manifest.edit` or `config.edit` row per write, the
`task.complete`, `task.commit` and `phase.signoff` rows derived from it, and a
`bash.unsandboxed` row for a Bash call run outside the sandbox. The hook keeps a
pre-image of each target it records under `stateDir`, which is what grew a busy
checkout's state directory into gigabytes; they are made only when the key is
`true` (`_config.journal_records_calls`).

What turning it on restores: every row and pre-image an unset key used to make
before 4.0.0, verified by `audit-journal.py verify` as before. Removing the key
from a config that set it `true` is recorded as the switch going off, by the
config edit's own last row. With it unset, a plan file changed by an edit tool or
a shell command rather than by a verb has no row explaining it, and
`audit-journal.py verify` warns that it changed since the last row that recorded
it until a verb's next row records its state again.

Each session start also clears `stateDir` of what is no longer read: the
plugin's own state files of every session whose end the usage hook recorded,
and, while calls are not recorded, every pre-image but the running session's - except a
still-running session's copy of the config, which an edit that turns recording off reads to
record that it did.
