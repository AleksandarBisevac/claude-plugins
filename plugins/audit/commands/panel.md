---
description: 'Audit pipeline: launch a local control panel (browser UI) to visually manage .claude/audit.config.json and the manifest''s composition levers (reviewSkill, per-task skills/models, buildCommands), with live validation and discovery of the skills & agents available in this repo + globally. Ephemeral, on-demand server — writes files on your explicit Save; Ctrl-C stops it.'
argument-hint: '[--port <n>] [--no-open]'
allowed-tools: Read, Bash
---

# /audit:panel — the control panel

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first for the config +
manifest conventions (preflight is read-only here: no git-root check, no lock — the
panel *itself* takes the lock only when it writes the manifest, and refuses if one is held).

Launch the panel:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/panel-server.py" --project "$(pwd)"
```

Pass `--port <n>` and/or `--no-open` through from `$ARGUMENTS` when given (otherwise a
free port is chosen and the browser opens automatically). Print the printed URL to the
user and tell them: **open it in a browser, and press Ctrl-C in this terminal to stop
the server when done.**

Because the command blocks while the server runs, launch it so its URL is visible and
the user can stop it (e.g. run it and surface the first lines of output, or advise the
user to run the command themselves with the `!` prefix). Do not background it silently.

## What the panel does (read-only summary for the user)
- **Guards & paths** — a form over `.claude/audit.config.json` (paths, `exemptGlobs`,
  `guardEdits.tokenVars` / `customRules`, `secretPatterns.extra`, `tddReminder`,
  `bashWriteCheck`), validated against `schema/audit-config.schema.json` via
  `validate-config.py`. Save writes the file atomically; invalid input is refused.
- **Composition** — set `meta.reviewSkill`, per-task `skills[]` and `model`, per-phase
  `review.model`, and `meta.buildCommands` — with **pickers populated by discovery** of
  the skills & agents actually available (project `.claude/`, `~/.claude/`, installed
  plugins). It writes back **only** these fields, validates via `validate-manifest.py`
  before writing, and **refuses while `<manifestPath>.lock` is held** (a running
  `/audit` command). It never adds/removes/reshapes phases, tasks, or bugs — use
  `/audit:task`, `/audit:bug`, `/audit:run` for that.
- **Overview** — the live rollup (phase progress, task/bug totals, ready count) and
  validation status.

Safety: binds `127.0.0.1` only, requires a per-launch token on every API call, and
refuses any write whose path escapes the project directory. It is a dev-time tool, not
a running service — nothing persists after Ctrl-C.
