# audit — a Claude Code plugin

A **manifest-driven, model-aware, test-driven** audit/fix pipeline for any repo, plus
three guard hooks (plan-first, secret-safety, token-logging). The pipeline logic is
generic; everything project-specific is supplied by a small per-repo config file.

## What you get

- **`/audit` slash command** — orchestrates phases → tasks from a JSON manifest. Per-task
  model + skills, TDD/regression/gate-only test discipline, branch-per-phase git flow,
  and gated phase sign-off (optional review skill + test gates + optional runtime boot).
- **Hooks:**
  - `require-plan.py` (PreToolUse: Edit/Write/MultiEdit) — non-trivial edits must be planned
    in the manifest or opted out via a single-use keyword.
  - `detect-plan-skip.py` (UserPromptSubmit) — arms that single-use opt-out when your prompt
    contains the bypass keyword.
  - `guard-secrets-read.py` (PreToolUse: Read/Grep/Bash) — blocks reading secret files
    (`.env`, credentials, signing material) and dumping env/token values.
  - `guard-edits.py` (PreToolUse: Edit/Write/MultiEdit) — blocks token-logging and any
    project-defined banned patterns.
- **`schema/audit-plan.schema.json`** — a JSON Schema (draft 2020-12) for the manifest, so
  editors and CI validate it.
- **`templates/`** — a config example and a starter manifest.

## Install

```bash
/plugin marketplace add <you>/claude-audit-plugin      # or a local path during dev
/plugin install audit@claude-audit-plugin
```

Then create the manifest and (optionally) the config in your repo:

```bash
mkdir -p docs/audit .claude
cp <plugin>/templates/audit-plan.starter.json docs/audit/audit-plan.json
cp <plugin>/templates/audit.config.example.json .claude/audit.config.json   # optional
```

Run it:

```bash
/audit status          # report, no changes
/audit next            # execute the next ready task
/audit phase P0        # run a whole phase, then sign it off
/audit review P0       # re-run a phase's sign-off
```

## Configuration (`.claude/audit.config.json`)

Optional. Absent → safe defaults. Read by the hooks from `${CLAUDE_PROJECT_DIR}`.

| Key | Purpose | Default |
|---|---|---|
| `manifestPath` | Path to the manifest | `docs/audit/audit-plan.json` |
| `exemptGlobs` | Globs exempt from plan-first | `docs/audit/**`, `**/*.md`, `.claude/**`, `**/*.spec.*`, `**/*.test.*` |
| `trivialLineThreshold` | Max added lines for the 1st free code file/session | `80` |
| `stateDir` / `logsDir` | Where state + bypass log live | `.claude/state` / `.claude/logs` |
| `bypassKeyword` | Single-use plan-first opt-out keyword | `#bez-plana` |
| `secretPatterns.extra` | Extra secret-path regexes (added to the built-in set) | `[]` |
| `guardEdits.tokenVars` | Identifier names treated as auth tokens | `accessToken`, `refreshToken`, `idToken` |
| `guardEdits.customRules` | Project banned patterns `{pathPrefix, bannedPattern, message}` | `[]` |

Manifest-level knobs live in the manifest's `meta` block (all optional): `developmentBranch`,
`branchPrefix`, `reviewSkill`, `runtimeBoot`, `nodePreamble`, `commit`, `buildCommands`,
`signOffChecklist`. See the schema for exact shapes and defaults.

## Extending (three layers, no plugin editing)

An installed plugin is read-only (a `/plugin update` overwrites in-place edits), so extend it via:

1. **Configure** — `.claude/audit.config.json` + manifest `meta.*`. Covers most per-project needs
   (globs, thresholds, branch, custom guard rules, token names, review skill, boot gate).
2. **Extend additively** — your repo's own `.claude/skills/`, `.claude/hooks/`, `.claude/agents/`
   compose with the plugin's. Add project skills/hooks without touching the plugin. (e.g. a project
   review skill stays in your repo; set `meta.reviewSkill` to its name and sign-off calls it.)
3. **Fork** — for deep changes, fork this repo or disable a plugin hook and ship your own. Rarely
   needed because the hooks are config-driven.

## The manifest in one minute

`meta` (global config) · `phases[]` (each with `tasks[]`) · `fileIndex` (file → task ids) ·
`deferred` · `proposals`. A task carries `model`, `skills`, `blockedBy`/`dependsOn`, `files`,
`tests` (`mode` + `add` + `gate`), `risk`, and orchestrator-written `status`/`commit`/`outcome`.
A phase runs on a `audit/<id>-<slug>` branch, commits per task, and merges fast-forward into
`meta.developmentBranch` after sign-off. Validate anytime:

```bash
npx ajv-cli validate -s schema/audit-plan.schema.json -d docs/audit/audit-plan.json
```
