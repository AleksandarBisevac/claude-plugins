---
description: 'Audit pipeline: open / stop / check a local control-panel UI to visually manage .claude/audit.config.json and the manifest''s composition levers (reviewSkill, per-task skills/models, buildCommands) — with live validation and discovery of the skills & agents available in this repo + globally. Ephemeral, on-demand; a per-project pidfile keeps it discoverable and stoppable.'
argument-hint: '[stop|status] [--port <n>]'
allowed-tools: Read, Bash
---

# /audit:panel — the control panel (open · stop · status)

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first (read-only preflight
1–2; no lock — the panel itself takes the manifest lock only when it *writes* the manifest,
and refuses if one is held). Let `PANEL="${CLAUDE_PLUGIN_ROOT}/scripts/panel-server.py"`.

**Dispatch on `$ARGUMENTS`:**

- **`stop`** → run `python3 "$PANEL" --project "$(pwd)" --stop` and print the result.
- **`status`** → run `python3 "$PANEL" --project "$(pwd)" --status` and print the result.
- **otherwise (open)** →
  1. Launch it **detached** so it survives this turn, passing `--port <n>` through from
     `$ARGUMENTS` if given:
     ```
     nohup python3 "$PANEL" --project "$(pwd)" >/dev/null 2>&1 &
     ```
  2. Wait ~1s, then read the live URL back:
     ```
     sleep 1; python3 "$PANEL" --project "$(pwd)" --status
     ```
  3. Tell the user, clearly: **the panel is RUNNING at `<the URL from --status>`** (their
     browser opens automatically), and **stop it anytime with `/audit:panel stop`** (or
     `/audit:panel status` to check). It's per-project — launching again just points at the
     already-running one, so it never leaves an untracked process behind.

**Prefer a visible terminal window?** (foreground, `Ctrl-C` to stop) — tell the user they can
run it themselves; in a Node repo `npm run panel` / `npm run panel:stop` is the shortcut,
otherwise `python3 "$PANEL" --project "$(pwd)"`.

## What the panel does (summary for the user)
- **Settings** — a form over the **whole** of `.claude/audit.config.json`, in four groups:
  *Paths & gate*, *Write guards*, *TDD reminder*, *Usage & pricing* — including the rate
  table, the cost bands and the TDD globs, which previously had no control at all. Each field
  is named by what it does with its JSON key beside it and an ⓘ hint; an empty field removes
  the key rather than writing a default. Regexes and the band pair are checked as you type;
  the save is decided by `validate-config.py`, which refuses invalid input, and writes
  atomically. Every "set X in the config" notice elsewhere in the panel links here.
- **Composition** — set `meta.reviewSkill`, per-task `skills[]` / `model`, per-phase
  `review.model`, `meta.buildCommands` — via an autocomplete **populated by discovery** of
  the skills & agents actually available (project `.claude/`, `~/.claude/`, installed
  plugins). Writes back **only** these fields, validates via `validate-manifest.py`, and
  **refuses while an `/audit` run holds a lock** (the index or any phase — see conventions →
  Concurrency lock). Never touches phases/tasks/bugs structure — use `/audit:task`,
  `/audit:bug`, `/audit:run` for that.
- **Overview** — the live rollup + validation status.

Safety: binds `127.0.0.1` only, requires a per-launch token on every API call, and refuses
any write whose path escapes the project directory. Ephemeral — it runs until you `stop` it.
