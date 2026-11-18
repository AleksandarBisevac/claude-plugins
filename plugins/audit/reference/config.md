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
3. at the **next close**, and at sign-off so a verdict after the last close is
   not dropped, reads the run for that commit (`gh run list`, one call):
   - completed `success`: said in the did-line, nothing filed;
   - completed `failure`, `timed_out` or `startup_failure`: files a `high` bug
     (`audit-task.py bug-add`) naming the branch, the commit and the run id
     and URL, so the release guard and the open-bug rule see it at once. If the
     bug cannot be filed the drive stops on that refusal and the run is read
     again at the next close;
   - any other conclusion: said, no bug;
   - still running, not listed yet, or unreadable: said, and nothing new is
     dispatched on top of it.

A push or dispatch that fails (no remote, no `gh`, no credentials) is said in
the did-line and tried again at the next close. The driver never prompts for
credentials and never reads stdin on these calls.

Not done by this key: reading which jobs and cases failed. The bug names the
run; its URL is where the failing jobs are.

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
