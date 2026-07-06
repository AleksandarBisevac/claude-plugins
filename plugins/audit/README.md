# audit — a Claude Code plugin

A **manifest-driven, model-aware, test-driven** audit/fix pipeline for any repo — with
task + bug tracking, multi-agent manifest generation, and guard hooks (plan-first,
secret-safety, token-logging, TDD nudge). The pipeline logic is generic; everything
project-specific is supplied by a small per-repo config file.

## What you get

- **`/audit`** — orchestrates phases → tasks from a JSON manifest. Per-task
  model + skills subagents, TDD/regression/gate-only test discipline, branch-per-phase git flow,
  and gated phase sign-off (optional review skill + test gates + optional runtime boot).
- **`/audit:init`** — multi-agent codebase audit that GENERATES the manifest: interview →
  recon → parallel read-only explorers → synthesized, schema-valid phases/tasks.
- **`/audit:task`** — add a tracked task interactively (id allocation, field initialization,
  fileIndex maintenance, revalidation).
- **`/audit:bug`** — report/list/close bugs; `fix` materializes a bug into a **red-first TDD
  task** (the repro test must fail before the fix) executed by `/audit`.
- **Hooks:**
  - `require-plan.py` (PreToolUse: Edit/Write/MultiEdit) — non-trivial edits must be planned
    in the manifest or opted out via a single-use keyword.
  - `detect-plan-skip.py` (UserPromptSubmit) — arms that single-use opt-out when your prompt
    contains the bypass keyword.
  - `guard-secrets-read.py` (PreToolUse: Read/Grep/Bash) — blocks reading secret files
    (`.env`, credentials, signing material) and dumping env/token values.
  - `guard-edits.py` (PreToolUse: Edit/Write/MultiEdit) — blocks token-logging and any
    project-defined banned patterns.
  - `remind-tdd.py` (PostToolUse: Edit/Write/MultiEdit) — **non-blocking** nudge when source
    changes with no test touched in the session; throttled, manifest-aware, configurable.
- **`schema/audit-plan.schema.json`** — a JSON Schema (draft 2020-12) for the manifest, so
  editors and CI validate it — plus `scripts/validate-manifest.py`, a dependency-free
  referential validator (unique ids, resolvable deps, bug↔task links) the commands run
  after every manifest mutation.
- **`templates/`** — a config example and a starter manifest.

## Install

```bash
/plugin marketplace add AleksandarBisevac/claude-plugins   # or a local path during dev
/plugin install audit@quality-gates
```

Then create the manifest — either **generate** it:

```bash
/audit:init            # interviews you, audits the codebase in parallel, writes the manifest
```

…or copy the starter and fill it in by hand:

```bash
mkdir -p docs/audit .claude
cp <plugin>/templates/audit-plan.starter.json docs/audit/audit-plan.json
cp <plugin>/templates/audit.config.example.json .claude/audit.config.json   # optional
```

Run it:

```bash
/audit status          # report (phases, tasks, bugs), no changes
/audit next            # execute the next ready task
/audit phase P0        # run a whole phase, then sign it off
/audit review P0       # re-run a phase's sign-off
/audit:task add "..."  # add a tracked task
```

## Bugs

```bash
/audit:bug add "Login crashes on empty email"   # report → BUG-1 (severity, repro, expected/actual)
/audit:bug list                                 # open/triaged/in_progress bugs
/audit:bug fix BUG-1                            # materialize a tdd task in a BF<n> bugfix phase
/audit run BF1.1                                # repro test red → fix → green → commit; bug flips to fixed
/audit:bug close BUG-2 wontfix                  # close with a justification
```

A bug is not a plan — bugs live in the manifest's top-level `bugs[]` until `fix`
materializes one into a task whose repro test **must fail on current code first**
(`tests.mode: "tdd"`, `expectRedFirst: true`). The orchestrator links them
(`bug.taskId ↔ task.bugId`) and flips the bug to `fixed` + `fixedIn: <sha>` when
the task commits.

## Configuration (`.claude/audit.config.json`)

Optional. Absent → safe defaults. Read by the hooks from `${CLAUDE_PROJECT_DIR}`.

| Key | Purpose | Default |
|---|---|---|
| `manifestPath` | Path to the manifest | `docs/audit/audit-plan.json` |
| `exemptGlobs` | Globs exempt from plan-first | `docs/audit/**`, `**/*.md`, `.claude/**`, `**/*.spec.*`, `**/*.test.*` |
| `trivialLineThreshold` | Max added lines for the 1st free code file/session | `80` |
| `stateDir` / `logsDir` | Where state + bypass log live | `.claude/state` / `.claude/logs` |
| `bypassKeyword` | Single-use plan-first opt-out keyword | `#no-plan` |
| `secretPatterns.extra` | Extra secret-path regexes (added to the built-in set) | `[]` |
| `guardEdits.tokenVars` | Identifier names treated as auth tokens | `accessToken`, `refreshToken`, `idToken` |
| `guardEdits.customRules` | Project banned patterns `{pathPrefix, bannedPattern, message}` | `[]` |
| `tddReminder.enabled` | Master switch for the non-blocking TDD nudge | `true` |
| `tddReminder.sourceGlobs` / `testGlobs` | What counts as source vs test files | common code / test patterns |
| `tddReminder.throttleMinutes` | Minimum gap between nudges | `10` |
| `tddReminder.inProgressPolicy` | Manifest interplay: `skip-gate-only` \| `skip-all` \| `warn-always` | `skip-gate-only` |

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
`bugs[]` (tracker; outside phases until materialized) · `deferred` · `proposals`. A task
carries `model`, `skills`, `blockedBy`/`dependsOn`, `files`, `tests` (`mode` + `add` + `gate`),
`risk`, optional `bugId`, and orchestrator-written `status`/`commit`/`outcome`.
A phase runs on a `audit/<id>-<slug>` branch, commits per task, and merges fast-forward into
`meta.developmentBranch` after sign-off. Validate anytime:

```bash
python3 <plugin>/scripts/validate-manifest.py docs/audit/audit-plan.json
```

or with the JSON Schema:

```bash
npx ajv-cli validate --spec=draft2020 -s schema/audit-plan.schema.json -d docs/audit/audit-plan.json
```
