---
description: 'Audit pipeline: prune the local feeds this plugin writes under logsDir — today the plan-gate events feed rendered by the panel Plan gate card. Removes rows that no longer belong (paths outside this repository, lines that are not JSON, optionally rows past an age you name), prints what went and what stayed, and never touches anything outside logsDir. This one WRITES: the verb is mandatory and --dry-run is the read-only half.'
argument-hint: 'prune [--older-than DAYS] [--dry-run] [--json]'
allowed-tools: Bash
---

# /audit:logs — clean the feeds this plugin writes

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-logs.py" --project "$(pwd)" $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize or re-tabulate it.** It already
renders one line per fact with an aligned label column, and the two counts it exists to
show are positional.

Pass `$ARGUMENTS` through unchanged. If the user typed no verb, pass `prune` — it is the
only one, and the command refuses a bare invocation on purpose (see below).

## What it prunes, and what it will not

The file is `<logsDir>/plan-gate-events.jsonl`: one JSON line per verdict the plan gate
reaches, written by the hooks and rendered by the panel's **Plan gate** card. `prune`
removes the rows that no longer belong, in three named classes:

- **outside this repository** — the row's `file` resolves outside the consuming repo. The
  plugin manages and references only that repo, so such a row is not the feed's to keep.
  These can no longer be *produced* (the gates allow an out-of-scope path before recording
  it), so what is left is history to clear.
- **unreadable** — the line is not a JSON object. The panel's reader already drops these
  silently, so they take up the file while showing up nowhere.
- **older than DAYS** — **only** when `--older-than` is given. There is no default, and
  that is a decision rather than an omission: the feed already self-trims by *size*, so age
  has no growth problem left to solve, and "old" is not the same claim as "does not
  belong" — a deny from last quarter is still a true record of this repo. A default here
  would be a number with no basis.

**The blast radius is one file.** Its path is derived from the same `logsDir` +
filename the writer uses, so no argument this command takes can widen it. The **journal**
(`docs/audit/journal/`) is deliberately out of reach: that is the tamper-evident trail, it
is append-only on purpose, and a command that could prune it could edit the evidence.

## What a prune cannot decide, and why it says so

Two of the feed's own writers were repaired: a `file` cell that held a whole shell command
(it is a digest, a byte length and a program name now) and a `reason` cell that held an
absolute path (it carries the same repo-relative spelling or `<outside-repo>` token the
`file` cell gets). **Neither repair reaches a row that is already on disk**, and nothing in
a row records which release wrote it — so this prune keeps them rather than guessing at a
shape and removing on the guess. Guessing would be worse than the gap: a tracked file whose
repo-relative path contains a space reads exactly like a program followed by an argument,
and a removed row is counted and never echoed, so nobody could tell what went.

So the output **says it** instead, and carries the number that makes it actionable:

- **`oldest`** — how far back the feed still reaches after this prune, in whole days. It
  prints only when a feed exists with rows left in it, and reads *no kept row carries a
  readable stamp* when none does: the feed starting today and no row being willing to say
  are different answers.
- the note under the counts, which is what `oldest` is for. **`--older-than DAYS` is the
  only lever that reaches those rows** — aim it past the point where this project upgraded.

If a user asks whether their feed is clean, that pair is the honest answer: the classes
above are decided on evidence, and this is the part that is not decidable at all.

## Reading the output

Both counts always print, including at zero, and so does every class that was actually
looked for — a number that appears only when it is non-zero cannot be told from a number
nobody computed. `state` separates a feed **nobody has written yet** from a feed that is
**empty**; both report zero and zero, and only one of them means the gate has never had
anything to say here.

**Removed rows are counted by class and never echoed.** The path in an out-of-repository
row is the thing being removed, and printing it would write it straight back into the
transcript this prune was asked to clean. If the user wants to see what would go, that is
what `--dry-run` is for — same counts, nothing written.

Exit code: **0** the prune ran (whatever the counts) · **1** it could not (the reason is on
the `REFUSED` line) · **2** a usage error.

## This command WRITES, and that is why it is not a doctor flag

`/audit:doctor` is read-only by construction — no lock, no mutation, safe mid-phase and in
CI — and this is the opposite. The verb is mandatory for the same reason: a bare
`/audit:logs` must not prune by default.

`--dry-run` is the read-only half if you want to look first. It reports the identical
counts and leaves the file byte-for-byte as it was.

## Doing the same from the panel

The panel's server exposes the same rule at `POST /api/gate-events/prune`
(`{"dryRun": true}` for the preview, `{"olderThanDays": N}` for the age pass), and the
**Plan gate** card that renders these rows now carries the control: an optional
*older than* box and a **Clean up…** button that previews with `dryRun` first and prunes
only after the confirm dialog. Same rule, same counts, same refusals — the card asks the
endpoint, it does not re-decide anything.

**The card is not the place to read what the prune could not decide.** It reports counts;
the section above — the `oldest` line and the note beside it — is printed by this command
and nowhere else. Point a user here when the question is whether the feed is *clean*
rather than how many rows went.

Related: `/audit:doctor`, `/audit:panel`, `/audit:status`.
