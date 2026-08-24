---
description: 'Audit pipeline: diagnose the setup before it bites — interpreter the hooks will use, git root, config, manifest + shard integrity, which plan-gate tier is active, submodule conflicts, build runners, whether hooks have ever fired, the usage ledger, whether the audit trail still holds, and whether the capability policy is inert, contradicted by the plan, or never enforced. Read-only, no locks, no mutations.'
argument-hint: '[--deep] [--json] [--color auto|always|never]'
allowed-tools: Bash
---

# /audit:doctor — is this setup actually working?

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-doctor.py" --project "$(pwd)" $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**
It already renders plain ASCII with one line per check, an indented `->` fix under anything
actionable, and a totals line. Re-narrating it costs tokens and loses the alignment that
makes the output scannable.

Pass `$ARGUMENTS` through unchanged (`--json` for a machine-readable form). Nothing here
needs interpreting on your side.

## `--deep` — hold the task commits against the journal

Off by default, and off is right for a routine run. `--deep` adds one arm to the
**completions** check: for each done task in the completion-record era that names both a
commit SHA and a journal row, it asks git whether that commit's tree actually contains the
journal file recording the task. That is one `git ls-tree` per such task, so the cost
scales with how much completed history the plan has — which is why it is opt-in rather
than always on. It writes nothing and takes no lock, exactly like the default run.

Its only verdict is a **WARNING** — `--deep: the task commit does not carry the journal
file that records it` — so it cannot turn a passing run into a failing one; a run that
exits 0 today still exits 0 with `--deep`. Reach for it when the question is about the
**audit trail** rather than the setup: the journal's git anchor only pins the journal files
the task commits actually carry, and the default run never looks at that.

## What to do with the result

Exit code is the summary: **0** healthy (warnings allowed), **1** one or more findings,
**2** a usage error. The three levels mean different things and should be treated
differently:

- **FINDING** — broken now. The named command or gate will fail. Fix these first; each one
  carries its own `->` fix line.
- **WARNING** — works today, will bite later. A missing manifest, no evidence the hooks have
  run, an empty ledger (told apart from a ledger nothing ever created — that one reads
  `no ledger yet` and names the path metering will write), a stale lock, journal files
  uncommitted for over a week (the git anchor only pins committed history), an area owner
  the ledger's author column has never seen (usually an identity written differently from
  what `usage.authorMode` records). Worth reading, not worth blocking on.
  It also covers a second, different thing: a fact this read-only command **could not
  establish**. The `sandbox` and `secret rules` rows read settings files, and managed
  policy plus a `--settings` flag outrank every file they can see — so "no file declares
  it" is reported as *not established*, never as *off*, and never fails the run. An
  explicitly disabled sandbox is a FINDING, because that one is read off a file.
- **OK** — checked and healthy. Included deliberately: knowing the plan gate is in `warn`
  rather than `deny` is as useful as knowing something is broken. The plan-gate line names
  the tier **and what put it there** — `planGate`, legacy `enforce`, or the graded ladder —
  and pinning `planGate: "observe"` while a phase is running is the one setting that warns,
  because it holds the gate below what the evidence would enforce.

The **layout** line is the other one worth reading rather than skimming: it names which of
the two manifest layouts is in use, **and what that layout costs**. Single-file is a supported
shape, not a pending upgrade — `/audit:layout` is how someone *changes* the layout, in either
direction, not how they fix it — so an OK line naming it is a statement of fact and must not be
relayed as a to-do. The line deliberately names no command for that reason; if the user reads
the cost and wants the other shape, that is when `/audit:layout` comes up.

The layout is read from the phase stubs (`_manifest_io.is_sharded()`), which is the one reading
the whole plugin shares. A `meta.version` of 3 with no stub carrying a `shard` is therefore a
FINDING about the two disagreeing, not a layout — relay it as a broken index, because that is
what every reader is already treating it as.

If the run reports **no hook state**, the most likely cause is not a broken hook but a
plugin that is installed yet not enabled for this project — check `/plugin` → Installed.

This command is **read-only**: it takes no lock, writes nothing, and never executes a
`meta.buildCommands` entry (it resolves the program each one names and reports whether that
program exists). It is safe to run mid-phase, and safe to run in CI.

**That is why cleaning up is a different command.** `/audit:logs prune` removes rows from
`<logsDir>/plan-gate-events.jsonl` — the feed the plan gate writes and the panel's Plan gate
card shows — and it writes, so it is not a flag here. If a user asks to clean that file,
point them there rather than reaching for this command.

Do not modify anything. Related: `/audit:status`, `/audit:init`, `/audit:panel`,
`/audit:usage`, `/audit:layout`, `/audit:logs`.
