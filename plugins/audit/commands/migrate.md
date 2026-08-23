---
description: 'Audit pipeline: LEGACY SPELLING of /audit:layout sharded — it still works and does exactly that. Kept so existing transcripts, runbooks and older docs resolve; new work should say /audit:layout <sharded|single-file>, which also goes back the other way.'
argument-hint: '[--dry-run] [--renumber] [--force]'
allowed-tools: Read, Bash, AskUserQuestion
---

# /audit:migrate — the legacy spelling of `/audit:layout sharded`

**This command still works.** It is an alias, kept because transcripts, runbooks and older
documents already say it. It does one thing: what `/audit:layout sharded` does.

**Do that, not something of your own.** Read
`${CLAUDE_PLUGIN_ROOT}/commands/layout.md` and follow it with the direction fixed to `sharded`,
passing `--dry-run` / `--renumber` / `--force` through from `$ARGUMENTS` unchanged. There is no
second procedure here on purpose: two copies of a preflight is one copy and one lie.

**Say the new name once, in the report — then get on with it.** Something like *"`/audit:migrate`
is the old name for `/audit:layout sharded`; both do this."* One line, not a lecture, and never a
refusal to run.

**Why it was renamed.** `migrate` names a version upgrade — the tool moving forward, dragging old
state along. This is not that. Single-file and sharded are two equally current shapes of the same
schema: installing a newer plugin never makes a layout change due, and staying on single-file never
makes a manifest legacy. The old name said otherwise every time someone read it, and it named only
the one direction — `/audit:layout` also assembles shards back into a single file.

**This alias will be removed in a future release.** When it goes, `/audit:migrate` stops being a
command and a runbook that says it fails at that line. Anything written down — a project runbook, a
CI comment, a team wiki — is worth changing to `/audit:layout sharded` now, while both spellings
work.
