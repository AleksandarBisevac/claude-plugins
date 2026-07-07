# audit — a Claude Code plugin

A **manifest-driven, model-aware, test-driven** audit/fix pipeline for any repo — with
task + bug tracking, multi-agent manifest generation, and guard hooks (plan-first,
secret-safety, token-logging, TDD nudge). The pipeline logic is generic; everything
project-specific is supplied by a small per-repo config file.

## What you get

- **`/audit`** — orchestrates phases → tasks from a JSON manifest. Per-task
  model + skills subagents, TDD/regression/gate-only test discipline, branch-per-phase git flow,
  gated phase sign-off (optional review skill + test gates + optional runtime boot), and a
  working **`resume`** for interrupted runs.
- **`/audit:init`** — multi-agent codebase audit that GENERATES the manifest: interview →
  recon → parallel read-only explorers → synthesized, schema-valid phases/tasks.
- **`/audit:task`** — add a tracked task interactively (id allocation, field initialization,
  fileIndex maintenance, revalidation).
- **`/audit:bug`** — report/list/close bugs; `fix` materializes a bug into a **red-first TDD
  task** (the repro test must fail before the fix) executed by `/audit`.
- **`/audit:sync`** — mirror bugs/tasks into **Azure DevOps work items** (`push`), import
  assigned ADO bugs (`pull`), or diff link state (`status`). Explicit, idempotent, one
  direction per invocation; `az boards` CLI contract with the azure-devops MCP tools as an
  optional fast-path.
- **`/audit report`** — self-contained HTML + Markdown status report (phase progress, task
  tables, bug rollup, ADO links) — publishable as a CI artifact.
- **CI without Claude** — `scripts/audit-status.py --json | --gate` turns the manifest into
  a pipeline gate (fails on validator findings, open high-severity bugs, blocked tasks —
  tunable via `--fail-on`); see `docs/examples/azure-pipelines.yml`.
- **Pinned-tool agents** (`agents/`) — the orchestrator spawns the plugin's own subagents
  instead of free-form ones: `audit-explorer` is **mechanically read-only** (no Edit/Write/
  Bash in its tool list — not a prompt request, a hard boundary), `audit-executor` has no
  web tools and no nested agents, `audit-reviewer` can analyze but cannot edit. Commands
  fall back to general subagents on older Claude Code versions.
- **Hooks** (all launched via `py-launch.sh`, which resolves `python3` → `python` → `py`;
  the blocking guards fail **loud** — a manual-approval prompt — if no interpreter exists;
  every hook has a 10 s timeout):
  - `require-plan.py` (PreToolUse + PostToolUse: Edit/Write/MultiEdit/NotebookEdit) —
    non-trivial edits must be planned in the manifest or opted out via a single-use keyword.
    "Non-trivial" = change magnitude (added lines, chars/200, or removed lines) over the
    threshold, or a second distinct file in a session. The bypass is **transactional**:
    observed before the edit, consumed only after it actually happens.
  - `detect-plan-skip.py` (UserPromptSubmit) — arms that single-use opt-out when your prompt
    contains the bypass keyword (and tells you); also warns once per session when
    `.claude/audit.config.json` is malformed (your custom rules would silently not apply).
  - `guard-secrets-read.py` (PreToolUse: Read/Grep/Bash) — blocks reading secret files
    (`.env`, credentials, signing material) directly or indirectly (`git show`, `source`,
    `cp`/`mv`), dumping env/token values, and shell writes into source files
    (`sed -i`, `tee`, `>` redirects) that bypass the plan gate.
  - `guard-edits.py` (PreToolUse: edits) — blocks token-logging, project-defined banned
    patterns, edits of the installed plugin's own files, and bypass-state forgery.
  - `guard-bash-writes.py` (PostToolUse: Bash + edits) — **non-blocking** git-status diff
    check: when a shell command modifies a source file that no tool edit and no
    `in_progress` task accounts for, the model is told — in-band — that it just sidestepped
    the plan gate (the statically-undecidable residual of the PreToolUse checks).
  - `remind-tdd.py` (PostToolUse: edits) — **non-blocking** nudge when source
    changes with no test touched in the session; throttled, manifest-aware, configurable.
  - Stale session state (incl. forgotten armed bypasses) is garbage-collected after 7 days.
- **`schema/audit-plan.schema.json`** — a JSON Schema (draft 2020-12) for the manifest, so
  editors and CI validate it — plus `scripts/validate-manifest.py`, a dependency-free
  referential validator (unique ids, dependency **cycles**, reciprocal bug↔task links,
  bidirectional fileIndex, typo warnings; exit 0 valid / 1 findings / 2 unreadable) the
  commands run after every manifest mutation.
- **`templates/`** — a config example and a starter manifest.

## Requirements

- **Claude Code** (plugin support).
- **Python 3.8+** reachable on PATH as `python3`, `python`, or `py` — the hooks and the
  validator are dependency-free stdlib scripts.
- **POSIX `sh`** for the hook launcher. On **Windows** that means running Claude Code
  inside **Git Bash** (which also provides `sh`); with `cmd`/PowerShell-only sessions the
  hooks surface as non-blocking errors instead of running.
- Optional: Node/`npx` for JSON-Schema validation with `ajv-cli` (skipped when absent);
  the `az` CLI + `azure-devops` extension for `/audit:sync`.

## Install

```
/plugin marketplace add AleksandarBisevac/claude-plugins   # or a local path during dev
/plugin install audit@quality-gates
```

Commands appear as `/audit`, `/audit:init`, `/audit:task`, `/audit:bug`. If they don't
show up immediately, run `/reload-plugins` (or restart the session).

## Installing arms global hooks

> **Read this before installing.** The five guard hooks activate in **every** project and
> session — before any manifest exists. That is the point (the guards are always-on), but
> it surprises people: in a repo with no audit manifest, the plan-first gate still allows
> only **one** small non-manifest-covered source file per session, then blocks the second
> with guidance (bypass: include `#no-plan` in your prompt — single-use, logged).
> Docs (`**/*.md`), tests (`**/*.spec.*`, `**/*.test.*`), `docs/audit/**` and `.claude/**`
> are always exempt.

Scope or turn it off:

- **Disable for one project:** `claude plugin disable audit@quality-gates` in that project
  (or `/plugin` → Installed → audit → Disable). Re-enable with `claude plugin enable`.
- **Soften instead of disabling:** raise `trivialLineThreshold`, extend `exemptGlobs`, or
  set `tddReminder.enabled: false` in that repo's `.claude/audit.config.json` (see
  Configuration below).
- **Uninstall completely:** `/plugin uninstall audit@quality-gates`.
- What each guard does with **no** config and **no** manifest: plan-first (as above),
  secret-read guard (active — you want this one), token-logging ban (active),
  TDD reminder (active, non-blocking, throttled).

## Quick start

Generate the manifest (recommended):

```
/audit:init            # interviews you, audits the codebase in parallel, writes the manifest
```

…or copy the starter and fill it in by hand (from your repo root, any terminal):

```bash
mkdir -p docs/audit .claude
curl -fsSL https://raw.githubusercontent.com/AleksandarBisevac/claude-plugins/main/plugins/audit/templates/audit-plan.starter.json -o docs/audit/audit-plan.json
curl -fsSL https://raw.githubusercontent.com/AleksandarBisevac/claude-plugins/main/plugins/audit/templates/audit.config.example.json -o .claude/audit.config.json   # optional
```

> The starter's `meta.buildCommands` are **npm examples** — replace them with your repo's
> real lint/test/typecheck commands. Inside a Claude Code session the installed plugin's
> files are also reachable at `${CLAUDE_PLUGIN_ROOT}` (that's how the commands invoke the
> validator); `claude plugin list` shows what's installed.

Run it:

```
/audit status          # report (phases, tasks, bugs, resumable phases), no changes
/audit next            # execute the next ready task
/audit phase P0        # run a whole phase, then sign it off
/audit review P0       # re-run a phase's sign-off
/audit resume          # continue an interrupted phase run
/audit report          # write audit-report.html + .md next to the manifest
/audit:task add "..."  # add a tracked task (--phase <id> to target a phase)
```

## Bugs

```
/audit:bug add "Login crashes on empty email"   # report → BUG-1 (severity, repro, expected/actual)
/audit:bug list                                 # open/triaged/in_progress bugs (list all | list <status>)
/audit:bug fix BUG-1                            # materialize a tdd task in a BF<n> bugfix phase
/audit run BF1.1                                # repro test red → fix → green → commit; bug flips to fixed
/audit:bug close BUG-2 wontfix                  # close with a justification
```

A bug is not a plan — bugs live in the manifest's top-level `bugs[]` until `fix`
materializes one into a task whose repro test **must fail on current code first**
(`tests.mode: "tdd"`, `expectRedFirst: true`). The orchestrator links them
(`bug.taskId ↔ task.bugId` — the validator enforces reciprocity) and flips the bug to
`fixed` + `fixedIn: <sha>` when the task commits.

## Configuration (`.claude/audit.config.json`)

Optional. Absent → safe defaults. **Present but malformed → defaults + a one-time
warning** (your custom patterns would otherwise silently not apply; `/audit` also refuses
to run until it parses). Read by the hooks from `${CLAUDE_PROJECT_DIR}`.

| Key | Purpose | Default |
|---|---|---|
| `manifestPath` | Path to the manifest | `docs/audit/audit-plan.json` |
| `exemptGlobs` | Globs exempt from plan-first | `docs/audit/**`, `**/*.md`, `.claude/**`, `**/*.spec.*`, `**/*.test.*` |
| `trivialLineThreshold` | Max change magnitude for the 1st free code file/session | `80` |
| `stateDir` / `logsDir` | Where state + bypass log live (add both to `.gitignore`) | `.claude/state` / `.claude/logs` |
| `bypassKeyword` | Single-use plan-first opt-out keyword | `#no-plan` |
| `secretPatterns.extra` | Extra secret-path regexes (added to the built-in set) | `[]` |
| `guardEdits.tokenVars` | Identifier names treated as auth tokens | `accessToken`, `refreshToken`, `idToken` |
| `guardEdits.customRules` | Project banned patterns `{pathPrefix, bannedPattern, message}` | `[]` |
| `bashWriteCheck.enabled` | PostToolUse git-status diff check for shell writes into source | `true` |
| `tddReminder.enabled` | Master switch for the non-blocking TDD nudge | `true` |
| `tddReminder.sourceGlobs` / `testGlobs` | What counts as source vs test files (source also feeds the shell-write guard) | common code (incl. `.ipynb`) / test patterns |
| `tddReminder.throttleMinutes` | Minimum gap between nudges | `10` |
| `tddReminder.inProgressPolicy` | Manifest interplay: `skip-gate-only` \| `skip-all` \| `warn-always` | `skip-gate-only` |

Manifest-level knobs live in the manifest's `meta` block (all optional): `developmentBranch`,
`branchPrefix`, `reviewSkill`, `runtimeBoot`, `nodePreamble`, `commit`, `buildCommands`.
See the schema for exact shapes and defaults. Per-phase, `desiredOutcome` states what
success looks like — `/audit` shows it, feeds it to task subagents, and sign-off must address it.

## Azure DevOps (optional)

Add `meta.ado` to the manifest and `/audit:sync` links the tracker to your board:

```json
"ado": { "organization": "<org>", "project": "<project>",
         "areaPath": null, "iterationPath": null,
         "types": { "bug": "Bug", "task": "Task" } }
```

- `/audit:sync push` — create/update work items from manifest bugs (add `tasks`/`all` for
  tasks); shows the plan and asks before the first write; write-back `ado: {id, url,
  lastSyncedAt}` per item makes re-runs converge.
- `/audit:sync pull` — import assigned, unlinked ADO bugs as manifest bugs (you pick which).
- `/audit:sync status` — read-only drift table (manifest state vs ADO state).

Auth belongs to `az login` (locally) or the `AZURE_DEVOPS_EXT_PAT` variable (CI) — the
plugin never stores or prints credentials. For pipelines, `docs/examples/azure-pipelines.yml`
shows the validate → gate → report flow.

## Repos without tests

"Test-driven" needs tests to drive. In a repo with **no test runner**, gate entries are
empty and `testGateGreen` passes **vacuously** — the discipline silently does nothing.
Do one of: set a real `meta.buildCommands.test` (add a runner first — even one smoke test),
or put explicit `"manual: <checklist>"` entries in `phase.testGate` so sign-off surfaces
human action items instead of green-lighting nothing. `/audit:init` detects your build
commands and will tell you when it finds none.

## Concurrency

Mutating subcommands (`next`, `run`, `phase`, `review`, `resume`) hold
**`<manifestPath>.lock`**: a second session is refused with the holder's info, and a stale
lock (>60 min — a crashed run) offers a confirmed takeover. `status` and `report` never
lock. Add `*.lock` in the manifest directory to `.gitignore`. The lock protects the
manifest — the working tree and branches are still shared, so one Claude session per clone
remains the recommendation.

## Extending (three layers, no plugin editing)

An installed plugin is read-only (a `/plugin update` overwrites in-place edits — and since
0.3.0 `guard-edits` blocks runtime self-edits too), so extend it via:

1. **Configure** — `.claude/audit.config.json` + manifest `meta.*`. Covers most per-project needs
   (globs, thresholds, branch, custom guard rules, token names, review skill, boot gate).
2. **Extend additively** — your repo's own `.claude/skills/`, `.claude/hooks/`, `.claude/agents/`
   compose with the plugin's. Add project skills/hooks without touching the plugin. (e.g. a project
   review skill stays in your repo; set `meta.reviewSkill` to its name and sign-off calls it.)
3. **Fork** — for deep changes, fork this repo or disable a plugin hook and ship your own. Rarely
   needed because the hooks are config-driven.

## The manifest in one minute

`meta` (global config) · `phases[]` (each with `tasks[]`, a `desiredOutcome`, a `testGate`) ·
`fileIndex` (file → task ids, validated bidirectionally) · `bugs[]` (tracker; outside phases
until materialized) · `deferred` · `proposals`. A task carries `model`, `skills`,
`blockedBy`/`dependsOn` (cycle-checked), `files`, `tests` (`mode` + `add` + `gate`), `risk`,
optional `bugId`, and orchestrator-written `status`/`commit`/`outcome`. A phase runs on an
`audit/<id>-<slug>` branch, commits per task, and merges into `meta.developmentBranch` after
sign-off (ff, or `--no-ff` with your confirmation when the branch advanced).

Validate anytime — in-session:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" docs/audit/audit-plan.json
```

or from any terminal (exit 0 = valid, 1 = findings, 2 = unreadable; also works from a
checkout of this repo as `python3 plugins/audit/scripts/validate-manifest.py <manifest>`):

```bash
curl -fsSL https://raw.githubusercontent.com/AleksandarBisevac/claude-plugins/main/plugins/audit/scripts/validate-manifest.py -o /tmp/validate-manifest.py
python3 /tmp/validate-manifest.py docs/audit/audit-plan.json
```

or against the JSON Schema:

```bash
curl -fsSL https://raw.githubusercontent.com/AleksandarBisevac/claude-plugins/main/plugins/audit/schema/audit-plan.schema.json -o /tmp/audit-plan.schema.json
npx ajv-cli validate --spec=draft2020 -s /tmp/audit-plan.schema.json -d docs/audit/audit-plan.json
```
