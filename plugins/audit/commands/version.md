---
description: 'Audit plugin version: which build is running, what the marketplace offers and whether it auto-updates, every installed copy, and the newest published release - each with where it was read - plus the exact commands to update. Read-only; one GitHub request unless --offline.'
argument-hint: '[--offline] [--json]'
allowed-tools: Bash
---

# /audit:version — which build is running, and is there a newer one

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-version.py" $ARGUMENTS
```

**Print its stdout verbatim, in your own reply and inside a fenced block** — a tool result is
collapsed behind the tool call, so running the command is not delivering it. Do NOT re-format,
summarize or re-tabulate it: every line carries the file or service it was read from, and a
summary that drops those sources drops the thing that makes the lines checkable.

Pass `$ARGUMENTS` through unchanged. `--offline` skips the network; `--json` prints one object.

## What it reads

- **running** — the `plugin.json` of the copy this command runs from, with its path.
- **marketplace** — the marketplace this copy was installed from, what that clone offers,
  when it was last refreshed, and whether it **auto-updates**. Read from Claude Code's own
  record (`known_marketplaces.json` under `CLAUDE_CONFIG_DIR`, else `~/.claude`) — a file Claude
  Code writes and does not document, which the line says. A copy run from a checkout names no
  marketplace, and says where it runs from.
- **installed** — every installed copy of this plugin, by scope and project, with those older
  than the running copy marked (`installed_plugins.json`, the same caveat).
- **published** — the newest release on the repository `plugin.json` names: one unauthenticated
  request to the GitHub API, five seconds at most, and nothing about your project is sent
  (`SECURITY.md` → *Outbound network*). An unreachable feed is reported as such.

## What it concludes

The verdict is drawn only from what was read: **up to date**, **a newer release is published**
(exit 1, so a script can ask), **running ahead** of the newest release (an unreleased build), or
**could not be asked** — never "up to date" when the feed did not answer. When a newer release
is published and the marketplace is known, it prints the commands:

```
claude plugin marketplace update <marketplace>
claude plugin update audit@<marketplace>
then restart Claude Code (or run /reload-plugins)
```

If auto-update is off for the marketplace, it says how to turn it on: **/plugin → Marketplaces**,
or `"autoUpdate": true` on the marketplace entry in settings (Claude Code checks after a
session starts). A team can declare it for everyone in the project's `.claude/settings.json`
under `extraKnownMarketplaces`.

Exit codes: 0 answered, 1 a newer release is published, 2 a usage error.
