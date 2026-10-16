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
