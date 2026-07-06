# Plugin build & handoff guide

This repository is a **standalone Claude Code plugin** that packages a manifest-driven
`/audit` fix-pipeline plus four guard hooks. It was extracted (de-coupled, IP-scrubbed)
from an internal project's `.claude/` tooling so it can be reused in **any** repo and
published on a personal marketplace. This single document is self-sufficient: it explains
every file, why its contents are shaped the way they are, how to finish/publish it, and how
to verify it. You should be able to complete the whole system from this file alone.

---

## 0. Provenance & the one rule that shaped everything

The command + hooks originally hardcoded one project's specifics (a dev branch name, an app
package id, a review-skill name, a `yarn nx` build, a listener rule for one library, manifest
paths). The extraction removed **all** of that. The design rule:

> **Nothing project-specific lives in the plugin.** Every such value is read from the
> *consuming* repo — either `.claude/audit.config.json` (hooks) or the manifest's `meta` block
> (the command) — with a safe generic default.

Because the plugin is meant to be **public**, this is also an IP requirement: the published
tree must contain zero client/company identifiers. Verify before publishing — substitute your
own source project's identifiers for the placeholders:

```bash
grep -riE '<client-name>|<internal-lib>|<bundle-id>' .   # must print nothing
```

---

## 1. Directory tree

```
claude-plugins/                           # this repo (personal, public)
  PLUGIN-BUILD-GUIDE.md                   # ← you are here
  LICENSE                                 # MIT
  .gitignore
  .claude-plugin/
    marketplace.json                      # marketplace listing (one plugin: "audit")
  plugins/
    audit/
      .claude-plugin/plugin.json          # plugin manifest (name/version/author/…)
      commands/
        audit.md                          # the /audit orchestrator (generic; reads meta.*)
        init.md                           # /audit:init — multi-agent manifest generation
        task.md                           # /audit:task — interactive task creation
        bug.md                            # /audit:bug — bug tracking (add|list|fix|close)
      hooks/
        hooks.json                        # wires the 5 hooks to events (${CLAUDE_PLUGIN_ROOT})
        _config.py                        # shared config loader + path/manifest helpers
        require-plan.py                   # plan-first enforcement
        detect-plan-skip.py               # arms the single-use plan-first bypass
        guard-secrets-read.py             # blocks reading secrets / dumping env
        guard-edits.py                    # blocks token-logging + project custom rules
        remind-tdd.py                     # non-blocking TDD nudge (PostToolUse)
      reference/
        manifest-conventions.md           # shared command conventions (ids, templates, revalidate)
      schema/audit-plan.schema.json       # JSON Schema (draft 2020-12) for the manifest
      scripts/
        validate-manifest.py              # dependency-free referential validator
      templates/
        audit.config.example.json         # per-repo hook config template
        audit-plan.starter.json           # minimal manifest skeleton with $schema
      README.md                           # end-user install/config/extend docs
```

Claude Code plugin mechanics used here (all confirmed against the plugin docs):
- `.claude-plugin/plugin.json` — only `name` is strictly required.
- `commands/*.md` — slash commands (invoked `/audit`; namespaced `/audit:audit` if needed).
- `hooks/hooks.json` — hook wiring; scripts self-reference with **`${CLAUDE_PLUGIN_ROOT}`** and
  read the consuming repo via **`${CLAUDE_PROJECT_DIR}`**.
- `.claude-plugin/marketplace.json` — marketplace root listing `plugins[].source`.

---

## 2. File-by-file logic

### `.claude-plugin/marketplace.json`
Marketplace root (`name: "quality-gates"` — everything in the suite is a gate: plan gate,
test gate, sign-off gate, secret guard. Note: Claude Code REJECTS marketplace names that
impersonate official ones, e.g. anything "claude-*" — the GitHub repo may be named
`claude-plugins`, but this `name` field may not). Lists the
plugin `audit` at `./plugins/audit`. Users add it with
`/plugin marketplace add AleksandarBisevac/claude-plugins`.

### `plugins/audit/.claude-plugin/plugin.json`
Plugin manifest. `name: "audit"` drives the command namespace (`/audit`, `/audit:init`,
`/audit:task`, `/audit:bug`). Author/homepage/license are filled. No `userConfig` is used —
per-repo config is a plain file the hooks read (simpler than install-time prompts for
structured config like globs/customRules).

### `plugins/audit/commands/audit.md`
The orchestrator, as a command with YAML frontmatter (`description`, `argument-hint`,
`allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep`). Logic preserved from the original:
readiness rule, branch-per-phase, per-task subagent spawn with model+skills, TDD/regression/
gate-only discipline, per-task commit, phase sign-off, resume-after-interruption, reporting.
**De-coupling:** it reads `meta.developmentBranch` / `branchPrefix` / `reviewSkill` (null → skip)
/ `runtimeBoot` (null → skip) / `nodePreamble` (null → run gates directly) / `commit` /
`buildCommands`. It hardcodes no branch, package id, skill, or build tool. New safety: honors
`task.maxAttempts` (default 3 → mark `blocked`) and states the orchestrator (not the subagent)
writes `outcome`.

### `plugins/audit/commands/init.md`, `task.md`, `bug.md`
The creation-side commands (invoked namespaced: `/audit:init`, `/audit:task`, `/audit:bug` —
short forms may collide with built-ins like `/init`). All three read
`reference/manifest-conventions.md` first and revalidate after every mutation:
- **init** — interview (dimensions/scope/branch/size) → read-only recon (detect
  `meta.buildCommands`) → parallel read-only explorer subagents (subsystem × dimension,
  cap 6, strict-JSON findings) → synthesis into phases/tasks (tests.mode by finding kind,
  model by risk) → Write + validate. Backs up an existing manifest before regenerating.
- **task** — `add "<title>" [--phase <id>]`: target-phase selection (done phases are
  immutable), full new-task template, id allocation, fileIndex maintenance.
- **bug** — `add` (BUG-<n>, severity/repro/expected/actual) · `list` (read-only) ·
  `fix` (materializes a `tdd` + `expectRedFirst` task into a rolling `BF<n>` phase,
  links `bug.taskId ↔ task.bugId`, hands off to `/audit run`) · `close` ([wontfix]).
  Execution stays exclusively in `/audit` — no second execution engine.

### `plugins/audit/hooks/hooks.json`
Maps events → scripts using `${CLAUDE_PLUGIN_ROOT}`:
- PreToolUse `Read|Grep|Bash` → `guard-secrets-read.py`
- PreToolUse `Edit|Write|MultiEdit` → `guard-edits.py`, then `require-plan.py`
- PostToolUse `Edit|Write|MultiEdit` → `remind-tdd.py`
- UserPromptSubmit → `detect-plan-skip.py`

### `plugins/audit/hooks/_config.py`
Shared, dependency-free config loader. `repo_root(data)` resolves the consuming repo
(`CLAUDE_PROJECT_DIR` → stdin `cwd` → `getcwd`). `load(root)` reads
`<root>/.claude/audit.config.json` and deep-merges it over `DEFAULTS`; **never raises** (returns
defaults on any error — hooks must not break legit work). Typed getters: `state_dir`, `logs_dir`,
`token_vars`, `custom_rules`, `extra_secret_patterns`, `tdd_reminder`. Also hosts the shared
path/manifest helpers (`rel_path`, `matches_exempt`, `strip_line_suffix`, `in_progress_files`,
`in_progress_task_map` — the latter exposes each covering task's `tests.mode` for remind-tdd).
Each hook does `sys.path.insert(0, dirname(__file__)); import _config`.

### `plugins/audit/hooks/require-plan.py`
Plan-first gate on Edit/Write/MultiEdit. ALLOW/BLOCK order: unknown tool/no path → allow; exempt
glob (config) → allow; file covered by an `in_progress` manifest task → allow; single-use bypass
armed → consume + log + allow; else first small (`<= trivialLineThreshold`) non-exempt file per
session → allow, a 2nd distinct file or an over-threshold change → **block** with guidance. All
tunables from config (`manifestPath`, `exemptGlobs`, `trivialLineThreshold`, `stateDir`,
`logsDir`, `bypassKeyword`). `_matches_exempt` understands `dir/**` and `**/*.ext` glob forms.
`--selftest` covers exempt/first-file/second-file/over-threshold/bypass paths (generic paths, no
project coupling).

### `plugins/audit/hooks/detect-plan-skip.py`
UserPromptSubmit logger. If the prompt contains `bypassKeyword` (config; default `#no-plan`),
writes `stateDir/plan-bypass-<session>.json` and appends to `logsDir/plan-bypass.log`. Never
blocks. `require-plan.py` consumes (deletes) that file on the next non-trivial edit — single-use.

### `plugins/audit/hooks/guard-secrets-read.py`
Read/Grep/Bash secret backstop. Blocks: reading secret file *contents* (`.env`, `credentials*`,
`.p12/.mobileprovision/.keystore/.jks/.p8/.pem`) via the Read tool, via Grep path/glob (Grep
prints file lines), via shell read-verbs, and via inline-eval one-liners (`python -c`, `node -e`,
…); also blocks `printenv`/`env` dumps and echoing token-like vars; best-effort blocks inline-eval
*writes* to non-exempt source (a known plan-first bypass vector). Listing NAMES stays allowed.
`secretPatterns.extra` (config) adds patterns. `--selftest` (29 cases) uses fictional paths only.

### `plugins/audit/hooks/guard-edits.py`
Edit/Write/MultiEdit content guard. (1) Runs `guardEdits.customRules` (config) — each
`{pathPrefix, bannedPattern, message}` blocks its regex under its path prefix; ships EMPTY (the
one-library listener rule that used to be hardcoded is now just an example in the config
template). (2) Token-logging ban built dynamically from `guardEdits.tokenVars` — blocks
`console.*`/`Sentry.*`/`remoteLog(… token …)` and `Bearer ${token}`, allowing `.slice` prefix
debug. `--selftest` builds its token test-input at runtime (`"access"+"Token"`) so this source
file itself never trips a token-logging guard.

### `plugins/audit/hooks/remind-tdd.py`
PostToolUse (Edit|Write|MultiEdit) **non-blocking** TDD nudge: when a SOURCE file changes and
no TEST file was touched this session, prints `hookSpecificOutput.additionalContext` (exit 0 —
never blocks; PostToolUse is the only event with a first-class non-blocking Claude-visible
channel). Records test-file touches BEFORE any warn logic (the hook watches its own Edit
stream — that ordering is the whole mechanism). Throttled (once per file + global
`throttleMinutes` gap) and manifest-aware: silent when the file is covered by an
`in_progress` `gate-only` task (`inProgressPolicy`: skip-gate-only | skip-all | warn-always).
All tunables under config `tddReminder`. `--selftest` (12 cases).

### `plugins/audit/reference/manifest-conventions.md`
Shared conventions every command reads first (lives OUTSIDE `commands/` so it can't register
as a command): manifest path resolution, the Edit-and-revalidate rule, id allocation
(task `<phase>.<n>`, bug `BUG-<n>`, bugfix phase `BF<n>`), status enums, new-task/new-phase
templates, fileIndex maintenance, done-phase immutability.

### `plugins/audit/scripts/validate-manifest.py`
Dependency-free referential validator the commands run after every manifest mutation —
checks the JSON Schema can't express: unique ids, resolvable `blockedBy`/`dependsOn`,
`fileIndex` integrity, `bugs[]` shape + `bug.taskId ↔ task.bugId` cross-links, enums.
Exit 0 clean / 1 with findings. `--selftest` (14 cases).

### `plugins/audit/schema/audit-plan.schema.json`
JSON Schema (draft 2020-12) for the manifest. Back-compatible: only `meta`/`phases` (and per-item
`id`/`title`/`status`) required; `additionalProperties: true` at object levels so a pre-existing
manifest validates unchanged after adding `$schema`. Enforces enums on `status`, `tests.mode`,
`risk`, review/finding `severity`. Encodes the **schema fixes**: documents the `tests.add`
tdd-vs-regression meaning + adds `expectRedFirst`; documents the `blockedBy` (hard gate) vs
`dependsOn` (intra-phase ordering) split; defines `finding` and `deferred.items` as
`string`-or-`object`; adds `task.maxAttempts`; documents that the orchestrator writes `outcome`;
adds `meta.buildCommands` and `meta.signOffChecklist` so gate strings and DoD aren't hardcoded.
v0.2.0 adds the optional top-level `bugs[]` (`$defs/bug`, `$defs/bugStatus`: open | triaged |
in_progress | fixed | wontfix) and `task.bugId` — all optional, back-compatible.

### `plugins/audit/templates/audit.config.example.json`
Copy to `<repo>/.claude/audit.config.json`. Every key optional. Contains an **illustrative**
generic `customRule` (a realtime/subscription `removeAllListeners` footgun) — replace or empty it.
No client identifiers.

### `plugins/audit/templates/audit-plan.starter.json`
Minimal manifest with `$schema`, a `meta` showing all new fields, one phase + one task. **TODO:**
set the `$schema` URL to your published raw path and fill `repo`/`createdISO`.

### `plugins/audit/README.md`
End-user docs: install, run, the config table, the three-layer extensibility model, and a
one-minute manifest overview.

---

## 3. Finish & publish — DONE (v0.2.0)

All of the original TODOs are resolved: `plugin.json` author/homepage/license filled,
`marketplace.json` owner filled + renamed to `claude-plugins`, starter `$schema` URL points at
this repo, MIT `LICENSE` + `.gitignore` added, git history initialized. Published at
`https://github.com/AleksandarBisevac/claude-plugins`. To release a new version: bump
`plugin.json` `version`, update §1/§2 if files changed, run §4, tag `v<version>`, push.

## 4. Verify

```bash
# 1. Hooks + validator pass their own selftests
python3 plugins/audit/hooks/require-plan.py --selftest
python3 plugins/audit/hooks/guard-edits.py --selftest
python3 plugins/audit/hooks/guard-secrets-read.py --selftest
python3 plugins/audit/hooks/remind-tdd.py --selftest
python3 plugins/audit/scripts/validate-manifest.py --selftest

# 2. Schema + validator accept the starter (and any real manifest)
python3 plugins/audit/scripts/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
npx ajv-cli validate --spec=draft2020 -s plugins/audit/schema/audit-plan.schema.json \
  -d plugins/audit/templates/audit-plan.starter.json

# 3. IP scrub — must print nothing (substitute your source project's identifiers)
grep -riE '<client-name>|<internal-lib>|<bundle-id>' .

# 4. End-to-end in a throwaway repo
/plugin marketplace add /abs/path/to/claude-plugins
/plugin install audit@quality-gates
#   generate the manifest with /audit:init (or copy the templates), then:
/audit status
#   edit a non-exempt file with no plan → require-plan blocks; add #no-plan (or your
#   bypassKeyword) → logged bypass; a custom rule blocks under its pathPrefix only;
#   edit a source file with no test touched → remind-tdd nudges (non-blocking).
/audit:bug add "..." ; /audit:bug fix BUG-1 ; /audit run BF1.1
```

## 5. How the pieces relate at runtime

**Creation**: `/audit:init` interviews you, fans out parallel read-only explorers, and
synthesizes the manifest; `/audit:task add` appends planned work; `/audit:bug add` records
bugs and `/audit:bug fix` materializes one into a red-first `tdd` task in a `BF<n>` phase.
Every mutation revalidates via `scripts/validate-manifest.py`.

**Execution**: `/audit` drives the manifest, spawning model-assigned subagents that load
`task.skills`, run `tests.gate`, and commit per task on a phase branch, then sign the phase
off (optional review skill + test gates + optional runtime boot) and ff-merge into
`meta.developmentBranch`. When a task carries `bugId`, its commit flips the linked bug to
`fixed` + `fixedIn`.

**Guard rails**: `detect-plan-skip` (on your prompt) arms a bypass → `require-plan` (on an
edit) consumes it or enforces the plan gate → `guard-edits` + `guard-secrets-read` block
token-logging/secret-reads → `remind-tdd` (after an edit) nudges toward test-first without
blocking. All project specifics come from `.claude/audit.config.json` (hooks) and `meta.*`
(commands).
