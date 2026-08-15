# Plugin build & handoff guide

This repository is a **standalone Claude Code plugin** that packages a manifest-driven
manifest-driven `/audit:*` fix-pipeline plus seven guard hooks and four pinned-tool agents. It was extracted (de-coupled, IP-scrubbed)
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
  README.md                               # repo landing page
  PLUGIN-BUILD-GUIDE.md                   # ← you are here
  CHANGELOG.md / SECURITY.md / CONTRIBUTING.md
  LICENSE                                 # MIT
.gitignore
.github/workflows/ci.yml                # selftests + validators on ubuntu/windows
  docs/audit/audit-plan.json              # DOGFOOD manifest: this repo's roadmap, CI-validated
  docs/audit/audit-report.html/.md        # rendered dogfood report (regenerated from the manifest)
  docs/index.html / demo-large.html       # GitHub Pages live demo (rendered reports)
  docs/screenshots/*.png                  # committed report + panel screenshots (tools/capture-screenshots.mjs)
  docs/examples/azure-pipelines.yml       # CI recipe: validate → gate → publish report artifact
  docs/ado-connector.md                   # ADO connector field guide (user-facing; tracker-sync.md stays the contract)
  examples/                               # worked acme-store example (manifest + rendered report)
.claude-plugin/
    marketplace.json                      # marketplace listing (one plugin: "audit")
  plugins/
    audit/
.claude-plugin/plugin.json          # plugin manifest (name/version/author/…)
      commands/                           # execution verbs (each thin; read reference/orchestrator.md)
        status.md doctor.md next.md run.md phase.md review.md resume.md report.md   # /audit:<verb>
        panel.md                          # /audit:panel — open/stop/status the control-panel UI
        migrate.md                        # /audit:migrate — single-file -> sharded manifest layout
        init.md                           # /audit:init — multi-agent manifest generation
        task.md                           # /audit:task — interactive task creation
        bug.md                            # /audit:bug — bug tracking (add|list|fix|close)
        sync.md                           # /audit:sync — Azure DevOps work-item sync
      agents/
        audit-explorer.md                 # mechanically read-only auditor (no Edit/Write/Bash)
        audit-executor.md                 # task executor (no web tools, no nested agents)
        audit-reviewer.md                 # sign-off reviewer (no edit tools)
        guide.md                          # answers questions about the plugin (Read/Grep/Glob, haiku)
      hooks/
        hooks.json                        # wires the 9 hooks to events (${CLAUDE_PLUGIN_ROOT})
        py-launch.sh                      # interpreter launcher: python3→python→py, fail-loud guards
        _config.py                        # shared config loader + path/manifest helpers
        require-plan.py                   # plan-first gate, graded on evidence (observe/warn/deny; Pre decides, Post commits state)
        detect-plan-skip.py               # arms the plan-first bypass + config-error warning + state GC
        guard-secrets-read.py             # blocks secret reads (direct+indirect) + shell source writes
        guard-edits.py                    # token-logging ban, custom rules, self-edit/forgery block
        guard-capabilities.py             # capability policy: which skills/subagents/MCP tools may run here
        guard-bash-writes.py              # PostToolUse git-status diff check (unplanned shell writes)
        remind-tdd.py                     # non-blocking TDD nudge (PostToolUse)
        journal-writes.py                 # PostToolUse: records manifest/config writes in the audit trail
        meter-usage.py                    # Stop/SubagentStop/SessionEnd: tails the transcript into the usage ledger
      reference/
        orchestrator.md                   # shared execution logic (preflight, lock, Execute-the-task, sign-off)
        manifest-conventions.md           # shared command conventions (ids, templates, revalidate)
        tracker-sync.md                   # tracker-sync contract (tracker-neutral half + the ADO binding)
      schema/
        audit-plan.schema.json            # JSON Schema (draft 2020-12) for the manifest
        audit-config.schema.json          # JSON Schema for .claude/audit.config.json (panel validation)
      scripts/
        _manifest_io.py                   # dual-format loader/writer (single-file OR index+shards)
        _areas.py                         # meta.areas registry + reviewSkill/skills resolution
        _policy.py                        # capability policy: shape, validation, required -> deny -> allow -> default
        _output.py                        # stdout/stderr that degrade a glyph instead of crashing
        _fmt.py                           # the one token/cost formatter, shared by usage + report + status
        _cli_fmt.py                       # the one place CLI color lives: --color resolution + paint roles
        _loader.py                        # the one way scripts/ loads a sibling script as a library, one cache policy
        _ui_theme.py                      # shared visual tokens (colour/spacing/type/labels) for report + panel
        _deps.py                          # the module layer table, checked against the real import graph every run
        usage_ledger.py                   # token-usage metering core: transcript scan, dedup, attribution
        validate-manifest.py              # dependency-free referential validator (cycles, links)
        validate-config.py                # validates .claude/audit.config.json against its schema
        audit-status.py                   # headless rollup + CI gate (--json/--gate)
        audit-doctor.py                   # /audit:doctor: read-only "is this working?" diagnostics
        audit-lock.py                     # the /audit concurrency lock as an executable acquire/release/status
        audit-task.py                     # /audit:task add doer: id allocation, full template init, lock+journal
        audit-usage.py                    # /audit:usage: token spend, attributed
        render-report.py                  # self-contained HTML+MD report (CI artifact)
        _report_ui.py                     # reads scripts/ui/report.{css,js} at import, assembles _CSS/_SCRIPT
        _report_html.py                   # HTML fragment builders for the report: escaping, chips, table cells
        _report_usage.py                  # the report's Usage section: ledger load + every chart over it
        migrate-manifest.py               # /audit:migrate doer: single-file -> sharded (backup+restore)
        panel-server.py                   # localhost control-panel web UI (config + composition)
        _panel_ui.py                      # reads scripts/ui/panel.{html,css,js} at import, assembles UI_HTML
        _panel_discovery.py               # discovers skills/agents/MCP servers this project can reach
        _panel_settings.py                # the Settings form's schema + the write-path key allow-lists
        _panel_state.py                   # the panel's READ side: everything GET /api/* answers with
        _panel_write.py                   # the panel's WRITE side: everything PUT /api/* actually does
        _help.py                          # zero-token self-description: schema field help + how-it-works topics
        gen-demo-manifest.py              # synthetic LARGE manifest fixture for demos/screenshots/CI
        gen-demo-usage.py                 # synthetic usage ledger fixture, consistent with a real manifest
        ui/                               # panel/report HTML+CSS+JS as real editor-highlightable files, no .py
        audit-journal.py                  # append-only hash-chained audit trail (append/verify/show)
      templates/
        audit.config.example.json         # per-repo hook config template
        audit-plan.starter.json           # minimal manifest skeleton with $schema
      README.md                           # end-user install/config/extend docs
```

Claude Code plugin mechanics used here (all confirmed against the plugin docs):
- `.claude-plugin/plugin.json` — only `name` is strictly required.
- `commands/*.md` — slash commands, namespaced `/<plugin>:<file>` → `/audit:status`, `/audit:run`,
  `/audit:phase`, `/audit:init`, … (this Claude Code version has no bare `/audit`; each verb is its
  own command file so nothing is invoked as the awkward `/audit:audit`).
- `hooks/hooks.json` — hook wiring; scripts self-reference with **`${CLAUDE_PLUGIN_ROOT}`** and
  read the consuming repo via **`${CLAUDE_PROJECT_DIR}`**.
- `.claude-plugin/marketplace.json` — marketplace root listing `plugins[].source`.

---

## 1a. Module map (generated)

The map below is the real static import graph of `scripts/*.py`, grouped into the layers
`_deps.py` defines — generator output, not hand-maintained prose, kept honest by a drift
lint in `_deps.py`'s own selftest. Regenerate it with `python3 plugins/audit/scripts/_deps.py --render`.

```
module map (8 layers, generated by _deps.py --render)

L0:
  _output

L1:
  _areas -> _output
  _cli_fmt -> _output
  _deps -> _output
  _fmt -> _output
  _loader -> _output
  _manifest_io -> _output
  _policy -> _output
  _ui_theme -> _output
  usage_ledger -> _output

L2:
  _panel_settings -> _loader, _output
  _panel_ui -> _output, _ui_theme
  _report_html -> _areas, _output, _ui_theme
  _report_ui -> _output, _ui_theme

L3:
  _help -> _areas, _loader, _output, _panel_settings, _policy, _ui_theme
  _report_usage -> _fmt, _loader, _output, _report_html

L4:
  _panel_discovery -> _help, _manifest_io, _output

L5:
  _panel_state -> _areas, _help, _loader, _manifest_io, _output, _panel_discovery, _policy

L6:
  _panel_write -> _areas, _manifest_io, _output, _panel_settings, _panel_state, _policy

L7:
  audit-doctor -> _cli_fmt, _loader, _output
  audit-journal -> _output
  audit-lock -> _output
  audit-status -> _areas, _cli_fmt, _fmt, _loader, _manifest_io, _output, _panel_discovery, _ui_theme
  audit-task -> _manifest_io, _output, _panel_write
  audit-usage -> _areas, _cli_fmt, _fmt, _loader, _output
  gen-demo-manifest -> _loader, _output
  gen-demo-usage -> _loader, _output
  migrate-manifest -> _loader, _manifest_io, _output
  panel-server -> _help, _manifest_io, _output, _panel_discovery, _panel_settings, _panel_state, _panel_ui, _panel_write, _ui_theme
  render-report -> _loader, _manifest_io, _output, _report_html, _report_ui, _report_usage, _ui_theme
  validate-config -> _loader, _output, _policy
  validate-manifest -> _areas, _manifest_io, _output
```

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
Plugin manifest. `name: "audit"` drives the command namespace (`/audit:status`, `/audit:run`,
`/audit:phase`, `/audit:init`, `/audit:task`, `/audit:bug`, `/audit:sync`, …). Author/homepage/
license/repository are filled. No `userConfig` is used —
per-repo config is a plain file the hooks read (simpler than install-time prompts for
structured config like globs/customRules).

### `plugins/audit/reference/orchestrator.md` + the execution verb commands (v0.7.0)
Since 0.7.0 the orchestrator is split: the shared logic lives in `reference/orchestrator.md`, and
each action is its own thin command file — `status.md`, `next.md`, `run.md`, `phase.md`,
`review.md`, `resume.md`, `report.md` → `/audit:status`, `/audit:next`, `/audit:run <id>`,
`/audit:phase <id>`, `/audit:review <id>`, `/audit:resume`, `/audit:report`. (This replaces the
old single `audit.md`, whose only invocation would have been the awkward `/audit:audit`.) Each verb
file is a few lines: frontmatter with QUOTED values (an unquoted description containing `: ` silently
drops ALL frontmatter), plus "read `orchestrator.md` + `manifest-conventions.md`, run this slice."
`orchestrator.md` holds: config resolution (incl. `meta.gitRoot`), preflight (config/manifest/
git-root/submodule/lock), guardrails, readiness rule, concurrency lock, branch-per-phase,
Execute-the-task (executor agent + TDD/regression/gate-only + infra-vs-test failure split +
per-task commit via `git -C <gitRoot>`), Phase sign-off (reviewer agent, test gate, runtime boot,
ff/`--no-ff` merge), resume, reporting. **De-coupling:** everything reads `meta.developmentBranch` /
`branchPrefix` / `gitRoot` / `reviewSkill` (null → skip) / `areas` (the monorepo registry a phase's
`area` tag names; resolution `phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`,
stated identically in `orchestrator.md`, `manifest-conventions.md` and `review.md`) /
`runtimeBoot` (null → skip) /
`nodePreamble` / `commit` / `buildCommands` — no hardcoded branch, package id, skill, or build tool.
Read-only verbs (`status`, `report`) skip the mutating preflight and never lock.

### `plugins/audit/commands/init.md`, `task.md`, `bug.md`
The creation-side commands (invoked namespaced: `/audit:init`, `/audit:task`, `/audit:bug` —
short forms may collide with built-ins like `/init`). All three read
`reference/manifest-conventions.md` first and revalidate after every mutation:
- **init** — interview (dimensions/scope/branch/size) → read-only recon (detect
  `meta.buildCommands`; detect a **workspace** — pnpm/yarn workspaces, turbo, nx, lerna,
  `go.work`, a Cargo workspace, a `.sln` — and propose `meta.areas`, skipped entirely when
  nothing matches so a single-app repo comes out unchanged) → parallel read-only explorer
  subagents (subsystem × dimension,
  cap 6, strict-JSON findings) → synthesis into phases/tasks (tests.mode by finding kind,
  model by risk, `area` tags from the registry) → Write + validate. Backs up an existing
  manifest before regenerating.
- **task** — `add "<title>" [--phase <id>]`: target-phase selection (done phases are
  immutable), full new-task template, id allocation, fileIndex maintenance.
- **bug** — `add` (BUG-<n>, severity/repro/expected/actual) · `list` (read-only) ·
  `fix` (materializes a `tdd` + `expectRedFirst` task into a rolling `BF<n>` phase,
  links `bug.taskId ↔ task.bugId`, hands off to `/audit:run`) · `close` ([wontfix]).
  Execution stays exclusively in the `/audit:*` verbs — no second execution engine.
- **sync** (v0.5.0) — `push [bugs|tasks|all]` · `pull` · `status`: mirrors manifest
  bugs/tasks into Azure DevOps work items via the `az boards` CLI (azure-devops MCP tools
  as an optional fast-path), configured by `meta.ado`; idempotent by design — the
  write-back `item.ado = {id,url,lastSyncedAt}` lands immediately after each create, so
  interrupted runs converge. One direction per invocation; confirmation before the first
  outward write; credentials never touched (az login / AZURE_DEVOPS_EXT_PAT).

### `plugins/audit/hooks/hooks.json`
Maps events → scripts, every entry running through
`sh "${CLAUDE_PLUGIN_ROOT}/hooks/py-launch.sh" <script> <ask|open>` with a 10 s timeout:
- PreToolUse `Read|Grep|Bash` → `guard-secrets-read.py` (fail mode **ask**)
- PreToolUse `Edit|Write|MultiEdit|NotebookEdit` → `guard-edits.py`, then `require-plan.py` (both **ask**)
- PreToolUse `Skill|Task|Agent|mcp__.*` → `guard-capabilities.py` (fail mode **ask**)
- PostToolUse `Edit|Write|MultiEdit|NotebookEdit` → `require-plan.py` (state commit), `remind-tdd.py`, `guard-bash-writes.py` (records tool edits), `journal-writes.py` (records manifest/config writes; all **open**)
- PostToolUse `Bash` → `guard-bash-writes.py` (the diff check; **open**)
- UserPromptSubmit → `detect-plan-skip.py` (**open**)

`py-launch.sh` resolves `python3` → `python` → `py` with shell builtins only and
`exec`s the script (stdin passes through once, exit code propagates). With NO
interpreter, `ask` mode emits `permissionDecision: "ask"` JSON — the guarded tool
call surfaces a manual prompt instead of silently proceeding (fail-LOUD); `open`
mode exits silently (advisory hooks must never block). Fail modes are hardcoded
here because reading config requires Python (chicken-and-egg).

### `plugins/audit/hooks/_config.py`
Shared, dependency-free config loader. `repo_root(data)` resolves the consuming repo
(`CLAUDE_PROJECT_DIR` → stdin `cwd` → `getcwd`). `load(root)` reads
`<root>/.claude/audit.config.json` and deep-merges it (deep-copied — no aliasing of DEFAULTS)
over `DEFAULTS`; **never raises**. An ABSENT config silently yields defaults; a
PRESENT-but-malformed one yields defaults **plus a `_configError` marker** that
detect-plan-skip surfaces once per session (a broken config must not silently drop custom
rules). Typed getters: `state_dir`, `logs_dir`, `token_vars`, `custom_rules`,
`extra_secret_patterns`, `tdd_reminder`. Also hosts the shared path/manifest helpers
(`rel_path`, `matches_exempt`, `strip_line_suffix`, `in_progress_files`,
`in_progress_task_map` — the latter exposes each covering task's `tests.mode` for remind-tdd).
Each hook does `sys.path.insert(0, dirname(__file__)); import _config`. `--selftest`.

### `plugins/audit/hooks/require-plan.py`
Plan-first gate on Edit/Write/MultiEdit/NotebookEdit, registered under BOTH PreToolUse and
PostToolUse. ALLOW/BLOCK order: unknown tool/no path → allow; exempt glob (config) → allow;
file covered by an `in_progress` manifest task → allow; single-use bypass armed → allow;
else first small (change **magnitude** = max(added lines, chars/200, removed lines)
`<= trivialLineThreshold`) non-exempt file per session → allow.
**An out-of-policy edit is then GRADED on evidence** via `_config.plan_gate_mode`, because
enforcing plan-first requires a plan to enforce against: no manifest → `observe` (tally it,
report once per session from `detect-plan-skip.py`, never block); manifest but no phase
`in_progress` → `warn` (PostToolUse `additionalContext`); manifest + a running phase →
**deny** (canonical `permissionDecision` JSON). `enforce: true` denies at every tier.
The warn tier deliberately does NOT emit a `permissionDecision` — there is no `allow` path in
this hook, and adding one would auto-approve the tool call and skip the user's own prompt.
`_config.manifest_state` reads the ASSEMBLED manifest: sharded index stubs carry no `status`,
so a raw index read would miss every running phase.
**Transactional state**: PreToolUse only observes (the edit may still be denied by a sibling
hook or the user); PostToolUse — which fires only after a successful edit — consumes the
bypass (logged), records the free-file slot, and appends to the observe tally. All tunables
from config (`manifestPath`, `exemptGlobs`, `enforce`, `trivialLineThreshold`, `stateDir`,
`logsDir`, `bypassKeyword`).
`--selftest`.

### `plugins/audit/hooks/detect-plan-skip.py`
UserPromptSubmit logger. If the prompt contains `bypassKeyword` (config; default `#no-plan`),
writes `stateDir/plan-bypass-<session>.json`, appends to `logsDir/plan-bypass.log`, and tells
the user (systemMessage) the bypass is live. Also surfaces `_configError` (malformed config)
once per session, and opportunistically garbage-collects session state files older than 7
days (incl. forgotten armed bypasses). Never blocks. `require-plan.py`'s PostToolUse pass
consumes (deletes) the bypass file after the next non-trivial edit actually happens —
single-use. `--selftest`.

### `plugins/audit/hooks/guard-bash-writes.py` (v0.6.0)
PostToolUse watcher — the "complete control" for shell writes the PreToolUse text
inspection cannot decide (upstream #29709). Edit-tool events RECORD the touched file;
Bash events diff `git status --porcelain -uall` against the session's last-seen dirty set:
a NEW dirty source file that is not exempt, not the manifest/lock, not tool-edited, and not
covered by an `in_progress` task triggers a non-blocking `additionalContext` warning (once
per file per session). Needs a git repo; git errors/timeouts (5 s) are silent. Config:
`bashWriteCheck.enabled` (default true). `--selftest` (14 cases incl. a real `git init`
integration case).

### `plugins/audit/agents/` (v0.6.0, a fourth in v0.31.0)
Four pinned-tool agents, three of which the commands spawn via `subagent_type` (with a
general-subagent
fallback for older Claude Code): `audit-explorer` (Glob/Grep/Read — mechanically read-only;
/audit:init fan-out), `audit-executor` (Read/Edit/Write/Glob/Grep/Bash/Skill — no web tools,
no nested agents; task execution and review fixes), `audit-reviewer`
(Read/Glob/Grep/Bash/Skill — no edit tools; sign-off review runs the project review skill
inside the agent so the diff stays out of the orchestrator's context). Tool lists are a hard
boundary that does not depend on subagent hook inheritance (#43772); the agent system
prompts carry the invariants (no commits, no stash, red-first discipline, JSON return
shapes) while spawn prompts add the per-task specifics.

The fourth, `guide` (qualified `audit:guide`; Read/Grep/Glob, `model: haiku`), is invoked by a **human**, not by
the pipeline: it answers questions about the plugin from the plugin's own README, reference
docs, schemas and SECURITY.md, with a citation per claim. It is deliberately not a skill —
a skill auto-triggers, and billing a model for a question `/api/help` already answers for
free is the failure mode this whole feature exists to avoid. `scripts/_help.py` reads its
frontmatter, so the panel's "Ask audit:guide" hint cannot advertise a tool the agent does not
hold, and the build fails if it ever gains one that writes.

### `plugins/audit/hooks/guard-secrets-read.py`
Read/Grep/Bash secret backstop. Blocks: reading secret file *contents* (`.env`, `credentials*`,
SSH private keys `id_rsa`/`id_dsa`/`id_ecdsa`/`id_ed25519`,
`.p12/.pfx/.mobileprovision/.keystore/.jks/.p8/.pem`) via the Read tool, via Grep path/glob (Grep
prints file lines), via shell read-verbs — including the indirect ones (`git show`/`cat-file`,
`source`/dot-source, and `cp`/`mv`/`rsync`/`install` relocating a secret) — and via inline-eval
one-liners (`python -c`, `node -e`, …); also blocks `printenv`/`env` dumps and echoing
token-like vars. Plan-first backstop for Bash writes: inline-eval writes AND the high-signal
shell write forms (`sed -i`, `tee`, `>`/`>>`/`1>`/`>|` redirects — heredoc redirects included) into
non-exempt source files not covered by an `in_progress` task (source extensions derive from
`tddReminder.sourceGlobs`). Listing NAMES stays allowed. `secretPatterns.extra` (config) adds
patterns. `--selftest` uses fictional paths only.

### `plugins/audit/hooks/guard-edits.py`
Edit/Write/MultiEdit/NotebookEdit content guard. (1) Path-based protection first: denies edits
of the INSTALLED plugin's own files (self-edit; dev-checkout exempt) and writes to
`plan-bypass-*` state files (bypass forgery). (2) `guardEdits.customRules` (config) — each
`{pathPrefix, bannedPattern, message}` blocks its regex under its path prefix; ships EMPTY (the
one-library listener rule that used to be hardcoded is now just an example in the config
template). (3) Token-logging ban built dynamically from `guardEdits.tokenVars` — blocks
`console.*`/`Sentry.*`/`remoteLog(… token …)` and `Bearer ${token}`, allowing `.slice` prefix
debug. `--selftest` builds its token test-input at runtime (`"access"+"Token"`) so this source
file itself never trips a token-logging guard .

### `plugins/audit/hooks/remind-tdd.py`
PostToolUse (Edit|Write|MultiEdit|NotebookEdit) **non-blocking** TDD nudge: when a SOURCE file changes and
no TEST file was touched this session, prints `hookSpecificOutput.additionalContext` (exit 0 —
never blocks; PostToolUse is the only event with a first-class non-blocking Claude-visible
channel). Records test-file touches BEFORE any warn logic (the hook watches its own Edit
stream — that ordering is the whole mechanism). Throttled (once per file + global
`throttleMinutes` gap) and manifest-aware: silent when the file is covered by an
`in_progress` `gate-only` task (`inProgressPolicy`: skip-gate-only | skip-all | warn-always).
All tunables under config `tddReminder`. `--selftest`.

### `plugins/audit/hooks/journal-writes.py` (v0.29.0)
PostToolUse (Edit|Write|MultiEdit|NotebookEdit) recorder: every edit-tool write to the
manifest (index or phase shard) or to `.claude/audit.config.json` appends one row to the
audit trail via `scripts/audit-journal.py`. NO stdout at all — a recorder that talks turns
every manifest edit into transcript — and every failure is silent, because a journal that
cannot be written must not break the write it was recording. A hook rather than an
instruction on purpose: a model that forgets to log a change leaves a gap that looks exactly
like a covered-up one. Config `journal.enabled`. `--selftest` (30 cases, incl. an end-to-end
append + verify).

### `plugins/audit/hooks/guard-capabilities.py` (v0.30.0)
PreToolUse (`Skill|Task|Agent|mcp__.*`) enforcer for the `policy` config block: which skills,
subagents and MCP tools may be used in this repo, optionally scoped to the monorepo areas with
work in progress. The rule itself is NOT here — `scripts/_policy.py` owns the resolution, the
panel previews it and the doctor checks it through the same function — so this file is the
enforcement half only. Inert by default and short-circuits before reading a manifest; every
refusal names the rule that produced it. `onViolation` picks deny / ask / warn, and warn is a
`systemMessage` rather than a `permissionDecision`, which would bypass the permission system.
Leaves a throttled marker in `stateDir` so `/audit:doctor` can say whether the matchers ever
reach it (subagent hook inheritance is not guaranteed). `--selftest` (26 cases).

### `plugins/audit/hooks/meter-usage.py`
Stop / SubagentStop / SessionEnd hook that turns transcript JSONL into usage-ledger rows.
Claude Code hands hooks a `transcript_path` but no token counts, so this tails that file
(plus the session's subagent transcripts) from a saved byte offset, attributes each message
to a phase/task, and appends aggregated rows — never blocking, and driven by file offsets so
it stays correct regardless of which of the three events fired. Config lives under
`.claude/audit.config.json` -> `usage` (enabled/ledgerDir/authorMode/backfillOnFirstRun/
maxScanBytes/pricing); the mechanics (dedup, attribution precedence) live in `usage_ledger.py`.

### `plugins/audit/scripts/_areas.py`
The `meta.areas` registry and everything that resolves against it. A phase's `area` tag (free
text, since v0.16) is only a grouping label; this module is where a tag becomes a thing with
properties — a `root`, a `description`, a `reviewSkill`, `skills` — and it implements, once, the
two precedence rules every surface quotes identically: `phase.reviewSkill ?? areas[tag]
.reviewSkill ?? meta.reviewSkill` for the review skill, and area-skills-then-task-skills
(deduped, area first) for the executor. Registration stays optional in both directions;
`review_skill_conflicts()` finds the case where a multi-tag phase's areas disagree, so a
tie-break decided by write order stays visible instead of silent.

### `plugins/audit/scripts/_policy.py` (v0.30.0)
The policy block's shape, defaults, validation and resolution — required → deny → allow →
default, with area rules scoped to phases in progress. The required set (audit's own commands,
skills and agents, which no policy can deny) is read off the plugin's own directory rather than
listed. `validate-config.py` delegates to `validate_policy` here; `panel-server.py` and
`audit-doctor.py` call `resolve` here. `--selftest` (60 cases).

### `plugins/audit/scripts/_output.py`
The one `safe_stdio()` guard against `UnicodeEncodeError` on a redirected Windows stream
(a piped/teed/captured stdout falls back to the legacy code page; an unprintable glyph then
raises instead of printing). Every `scripts/` entry point calls it as its first statement,
enforced rather than remembered — `entries_missing_guard()` reads the directory and names any
`__main__` block that skips it. `hooks/` deliberately does not import this module: its only
output is `json.dumps` (ASCII by construction) plus its own selftest.

### `plugins/audit/scripts/_fmt.py`
The one token/cost/count formatter, unifying three copies that had drifted (`audit-usage.py`,
`render-report.py`, and `audit-status.py`'s importlib re-use of `audit-usage`'s). `fmt_tokens`/
`_fmt_tokens` share the same magnitude table (`B`/`M`/`K`) with a `dp` precision knob for the
report's label-vs-tooltip need; `fmt_cost`/`_fmt_cost` share the "never render real spend as
$0.00" rounding rule; `fmt_int` is the thousands-grouped form for countables that should never
be compacted. Golden values from both call sites were frozen into the selftest before either
was touched.

### `plugins/audit/scripts/_cli_fmt.py`
The one place CLI color lives, consumed by `audit-usage.py`, `audit-status.py` and
`audit-doctor.py` (each grew a `--color auto|always|never` flag, default auto). Mode
resolution: `never` is plain; `always` paints even under `NO_COLOR` (the flag is the more
explicit signal — pinned in the selftest); `auto` paints only when stdout is a TTY and
`NO_COLOR` is absent or empty, so the model-facing pipe stays plain. Five roles
(`ok`/`warn`/`finding`/`header`/`dim`), pure-ASCII SGR escapes, and a disabled `Painter`
that returns its input unchanged — which is what keeps every consumer's plain mode
byte-identical to its pre-color output (`strip(paint(x)) == x` is pinned).

### `plugins/audit/scripts/_loader.py`
The one way `scripts/` loads a sibling script as a library, replacing roughly fourteen
hand-rolled `importlib` copies that had drifted into five different caching policies.
`load(path, cache=True)` keeps a single process-wide memo keyed by the realpath, so two
different spellings of the same file share a cache entry; `cache=False` gets a fresh module
object for a selftest that mutates its target. Failures are never swallowed here — a missing
file or an import-time exception propagates, and a caller that wants a soft-fail catches it
itself. `hooks/` keeps its own two loader copies rather than importing this module, since hooks
must not depend on `scripts/` being on the launcher's path.

### `plugins/audit/scripts/_ui_theme.py`
The shared visual system — colour tokens (light + both dark forms), spacing, type, motion and
status-label vocabulary — imported by both the report renderer and the control panel so the two
surfaces read as one product instead of two hand-kept copies that had already drifted (a 1rem
gap between their nav-column widths, one example). `label()` maps a machine value like
`in_progress` to the words a person reads, with a graceful fallback for anything unknown. The
CSS lint helpers that police the stylesheet live alongside it.

### `plugins/audit/scripts/_deps.py` (P15.1)
The module import-layer table, checked against the real graph instead of trusted as prose:
`LAYERS` groups every `scripts/*.py` basename so a file may import a sibling only in a strictly
LOWER layer, and hooks/ may import nothing from scripts/ at all. `import_graph()` reads the real
edges via `ast` (not a regex — a nested or selftest-only import is still a real edge);
`layer_violations()` and `map_drift()` compare that graph and this guide's own module map /
directory tree / file-by-file sections against the truth, so the guide cannot silently drift
out from under the code it documents. The hooks rule has **no allow-list** — it had one entry,
this module's first run found it (`hooks/_config.py` reached `_manifest_io` by putting `scripts/`
at the front of `sys.path`), and it was fixed rather than kept, so `hooks_rule_drift()` now fails
the build on any document that states the rule and then carves an exception out of it. `--selftest`.

### `plugins/audit/scripts/usage_ledger.py`
The token-usage metering core `meter-usage.py` and `audit-usage.py --backfill` both call.
Claude Code hands hooks a `transcript_path`, not token counts, so this reads the transcript
JSONL directly — `message.usage` alongside `message.model`/`timestamp`/`gitBranch`/`sessionId`,
plus each subagent's sibling `subagents/agent-<id>.jsonl` + `.meta.json`. The one correctness
trap it exists to close: a single `message.usage` block repeats across every transcript entry
sharing a `message.id`, so naive summation overcounts spend by roughly 2.4x — this module dedups
by `message.id` within and across scans. Attribution runs task -> phase -> window ->
unattributed, highest precision first, nothing ever dropped.

### `plugins/audit/scripts/audit-journal.py` (v0.29.0)
The trail itself: `append(project, entry) -> bool` plus `append | verify | show` on the CLI.
One file per writer per month (`<journal dir>/<YYYY-MM>.<writerId>.jsonl`, default beside the
manifest) so parallel worktrees never conflict; each row carries `{v, ts, actor, action,
target, summary, stateHash, prev, hash}`, sha256 over canonical JSON, with the first row's
`prev` derived from the file's own base name so a file cannot be renamed into another
writer's slot. `verify` reports an edited / deleted / reordered row as a FINDING (exit 1) and
a torn tail or out-of-band drift as a WARNING (exit 0). **Tamper-evident, not tamper-proof** —
stated in the module, the README, the panel's own Settings card and SECURITY.md, because a
forger who rewrites the whole file still verifies. `append()` never raises. `--selftest`.

### `plugins/audit/scripts/gen-demo-manifest.py`
Generates the synthetic LARGE manifest fixture behind `docs/demo-large.html` and the panel
screenshots, on demand instead of committing it — the same flags always produce the same
bytes, so CI builds it, captures from it, and discards it, and nothing drifts the way the
uncommitted original did. `gen-demo-manifest.py <out-dir> [--phases 50] [--tasks 20] [--seed
11] [--single-file]` deliberately carries every state a reader can filter on (all phase/task
statuses, `blockedBy`, `dependsOn`, budgets over/under, `area` tags, a full bug lifecycle),
deterministically (fixed seed, no wall-clock) and validator-legal by construction (a `done`
phase never contains an unfinished task). `--selftest`.

### `plugins/audit/scripts/gen-demo-usage.py`
Generates a synthetic usage ledger consistent with a real manifest — task/phase ids that exist,
timestamps inside each task's own `startedAt`/`completedAt` window — so the report's Usage
section (and its screenshots) show something worth looking at instead of the empty state a
manifest with no spend produces. `gen-demo-usage.py <manifest> [--out-dir DIR] [--seed N]
[--authors a,b,c] [--adhoc-days N]` is deterministic (fixed seed, no unseeded random) and maps
a manifest's illustrative model tier to the concrete ledger model id the runtime actually
records. `--selftest` pins determinism and referential integrity against the manifest.

### `plugins/audit/reference/manifest-conventions.md`
Shared conventions every command reads first (lives OUTSIDE `commands/` so it can't register
as a command): manifest path resolution, the Edit-and-revalidate rule, id allocation
(task `<phase>.<n>`, bug `BUG-<n>`, bugfix phase `BF<n>`), status enums, new-task/new-phase
templates, fileIndex maintenance, done-phase immutability.

### `plugins/audit/scripts/validate-manifest.py`
Dependency-free referential validator the commands run after every manifest mutation —
checks the JSON Schema can't express: unique ids, resolvable `blockedBy`/`dependsOn`,
dependency **cycles** (incl. task-blocked-by-own-phase deadlocks), **bidirectional**
`fileIndex ↔ task.files` integrity, `bugs[]` shape + **reciprocal**
`bug.taskId ↔ task.bugId` cross-links, enums, plus non-fatal WARNINGs for unknown/typo'd
keys (did-you-mean) and pre-0.3 status combinations.
Exit 0 clean (warnings allowed) / 1 findings / 2 usage-or-unreadable. `--selftest`.

### `plugins/audit/scripts/audit-status.py` (v0.5.0)
Headless rollup + CI gate, stdlib-only; imports validate-manifest.py as a library via
importlib. `--json` prints the machine-readable summary (phases done/total, tasks/bugs by
status, ready-task list mirroring /audit's readiness rule); `--gate` exits 1 on tripped
conditions — default `invalid,open-high-bugs,blocked-tasks`, tunable with `--fail-on`
(also `open-bugs`, `in-progress` for release freezes). `--submodules <.gitmodules> [--git-root
<prefix>]` (v0.6.2) is the submodule preflight guard — exit 1 when any `task.files` entry lives
inside a git submodule (which the parent repo cannot stage/commit). Exit 0/1/2. `--selftest`
.

### `plugins/audit/scripts/audit-doctor.py`
`/audit:doctor`'s "is this working?" diagnostics — every check reuses an existing
implementation (`validate-config.validate_config`, `validate-manifest.validate`,
`audit-status.submodule_conflicts`, `usage_ledger.find_ledger_dir`) rather than
reimplementing it, so a rule never means one thing here and another at the gate. It is
read-only by construction: it never writes, never takes a lock, and for `buildCommands`
resolves whether the named executable exists rather than running it. Output classes match the
rest of the plugin (OK/WARNING/FINDING); exit 0 healthy, 1 findings, 2 usage error.

### `plugins/audit/scripts/audit-lock.py`
The `/audit` concurrency lock as an executable decision instead of orchestrator prose:
`acquire <name>`, `release <name>`, `status`, over the two tiers the orchestrator uses
(`index`, `phase-<id>`). Liveness, not age, decides a stale lock — a holder that is still
running is refused (exit 3); a holder that is not alive can be seized with `--takeover`
(exit 4) — because the old "older than 60 minutes = crashed" rule was wrong in both
directions. `--session`/`--pid` override the identity written into the lock for testing.

### `plugins/audit/scripts/audit-task.py` (v0.37.0)
The non-interactive `/audit:task add` doer. The command used to dictate the conventions'
15-field new-task template into the model's hands per add — a class of error (a missed field,
a misspelled enum, a fileIndex nobody extended) this script deletes: the command gathers
answers, the script writes them the same way every time. `add "<title>"` allocates the id
under the INDEX lock (`<phaseId>.<n>` over the whole assembled manifest plus parked-proposal
reservations; gaps are never re-minted), initializes every template field exactly once,
extends `fileIndex` for `--files`, heals a pending phase holding an in_progress task
(v0.37 A4, reused from `_panel_write`), writes through `_manifest_io` with
`_panel_write._write_back`'s footprint (touched shard + index only when fileIndex changed),
re-validates FROM DISK and rolls every written file back byte-for-byte on findings (exit 1),
and appends a `task.add` journal row in-process (the journal-writes hook only sees edit
TOOLS, not `os.replace` — same blindness `_panel_write._journal` covers). `--phase` absent
resolves the single in_progress phase or exits 2 naming the choices; `--skills null` writes
the explicit JSON-null opt-out (v0.37 B1); a held lock prints audit-lock's own message
(exit 3 live / 4 stale, `--takeover` to seize what a human confirmed dead).

### `plugins/audit/scripts/audit-usage.py`
`/audit:usage` — token spend, attributed, rendering its own final ASCII output (no box
drawing, no ANSI, no emoji) so the command file can print it verbatim without paying a model
to reformat a JSON rollup. With `--by phase|task|model|author|agent|day|hour|session|branch|
attr` it prints one focused table; without it, the full dashboard. `--backfill` re-reads every
transcript for the project from offset 0 and rebuilds the ledger — idempotent, and the only
path that rewrites (and therefore locks) rather than only appending.

### `plugins/audit/scripts/_manifest_io.py` + `migrate-manifest.py` + `commands/migrate.md` (v0.15.0)
The **sharded manifest layout**. `_manifest_io.py` is the dependency-free dual-format loader/writer:
`load_manifest` reads BOTH the legacy single file and the v3 index+shards form into the same assembled
dict (so every script + hook stays format-agnostic — it's wired into all five scripts' `main()` and
`hooks/_config.in_progress_task_map`); `split_manifest`/`save_sharded` write the sharded form (index of
`{id,title,shard}` stubs + `phases/<id>.json` bodies) atomically. The index stub carries NO runtime
mirror, so a phase run writes only its shard → parallel phase branches merge with no manifest conflict.
`migrate-manifest.py` (driven by `/audit:migrate`) converts single-file → sharded: validate source →
refuse mid-run (unless `--force`) → backup `.bak-<UTC>` → write → re-validate → restore on failure;
`--renumber` repairs duplicate `BUG-` ids, `--dry-run` previews. Locks moved to the shared git dir
(two-tier: index + per-phase-shard); ids allocate under the index lock; bug status is derived from the
linked task (so runs never write `bugs[]`). Schema bumped to v3 (phase requires only `id`/`title`; adds
`shard`/`claim`). Fully back-compat — v2 manifests keep working, migration is opt-in.

### `plugins/audit/scripts/render-report.py` (v0.5.0)
Manifest → self-contained `audit-report.html` + `.md` (inline CSS, zero network fetches):
phase progress bars, task tables, bug rollup, ADO links. Consumes audit-status's rollup
(single source of truth). Every manifest string is HTML-escaped — manifest content is
untrusted — and only http(s) URLs render as links (`javascript:` degrades to text).
The report's CSS/JS live as real files under `scripts/ui/report.{css,js}`; `_report_ui.py`
reads them at import with explicit utf-8 and assembles the same `_CSS`/`_SCRIPT` constants
byte-identically — the rendered report page stays a single self-contained file regardless.
`--selftest` (includes XSS cases).

### `plugins/audit/scripts/_report_ui.py`
The report's CSS and inline JS, off disk as real files under `scripts/ui/report.{css,js}`,
mirroring `_panel_ui.py`'s split so both surfaces follow one convention. `render-report.py`
used to carry `_CSS`/`_SCRIPT` as raw-string literals (plain CSS plus `_ui_theme.TOKEN_CSS`,
and a whole `<script>...</script>` block) that no editor highlighted and no linter looked at;
this module reads the real files at import with explicit utf-8 and reassembles the same two
constants byte-identically, so the rendered report page stays one self-contained file even
though its source no longer is.

### `plugins/audit/scripts/_report_html.py`
Pure HTML fragment builders moved out of `render-report.py`: escaping, chips/badges, table
cells and the filter panel, over already-computed values only — no layout decisions, no usage
data, no whole-document assembly (that stays in `render_html`/`render_md`, which call these
dozens of times and glue the fragments together). Every manifest value is untrusted JSON, so
each fragment routes through `e()` before it reaches the page, and `_safe_url` is the one gate
a URL passes before it may become an `href`. `render-report.py` keeps thin aliases so its
existing call sites and selftest are unchanged.

### `plugins/audit/scripts/_report_usage.py`
The report's Usage section, moved out of `render-report.py` as its largest single block:
`_usage_section` builds the HTML, `_usage_md` the Markdown twin, both off the dict
`load_usage()` reads from the usage ledger — tiles, trend, ranked lists, budgets, small
multiples, phase stacks, economics, routing and a heatmap as private fragment builders over
already-computed numbers. Two rules shape it: restraint on first paint (one dominant chart plus
three ranked lists, the rest behind disclosure), and every number states its basis (rate date,
attribution coverage, sample size) or it does not render. Formatting delegates to `_fmt.py`.

### `plugins/audit/commands/panel.md` + `plugins/audit/scripts/panel-server.py` (v0.13.0–v0.14.0)
`/audit:panel` opens a **localhost web UI** to manage the plugin without hand-editing JSON.
`panel.md` dispatches on its argument — bare = open (launched detached via `nohup … &`), `stop`,
`status`, `--port <n>` — and `panel-server.py` is a single dependency-free Python-stdlib HTTP
server (the UI's HTML/CSS/JS lives as real files under `scripts/ui/panel.{html,css,js}`;
`_panel_ui.py` reads them at import with explicit utf-8 and assembles the same `UI_HTML` constant
byte-identically — the served page is still one self-contained HTML file, the source just is not.
It reuses the plugin's pure cores — `validate-manifest.py`, `validate-config.py`,
`audit-status.py`, `hooks/_config.py` — via importlib). It binds `127.0.0.1`, checks the Host header, and requires a random per-launch token
on every `/api/*` call (`X-Audit-Token`/`?t=`); it tracks **one panel per project** via a
`.claude/audit-panel.json` pidfile (open/stop/status; stale pidfiles auto-cleaned). Four tabs:
**Settings** (a form over the WHOLE of `.claude/audit.config.json` in four groups, described
once by `SETTINGS_GROUPS`/`FIELD_HELP` in `panel-server.py` and rendered from that — the
coverage is asserted against `validate-config.py`'s own key sets, so a new config key with no
control fails the selftest), **Composition** (a compact, collapsible, **filterable** table of phases ·
tasks · per-task skills/model + per-phase review model, scaling to ~50×20, plus a discovered
"building blocks" sub-section — skills/agents/mcp — feeding the autocomplete), and **Overview**
(the live rollup + validation banner). Writes **only** config + composition fields — never
structural manifest CRUD, and never while a `/audit` run holds `<manifestPath>.lock` — validating
before each atomic save. `--selftest` covers the front-matter parser, discovery, and the server.

### `plugins/audit/scripts/_panel_ui.py`
The panel's markup/CSS/JS, off disk as real files under `scripts/ui/panel.{html,css,js}`.
`panel-server.py` used to carry the whole page as one raw-string literal (~820 lines of CSS,
~28 of body markup, ~2,913 of JS, none of it Python — no editor highlighted it, no linter
looked at it). `raw_template()` reads the three files and splices css/js back into two
insertion markers in the HTML, returning the exact string `panel-server.py`'s own
`.replace()` substitution chain (theme tokens, labels, settings, field help, config enums)
still runs on — byte-for-byte, before per-request values like the audit token are filled in.

### `plugins/audit/scripts/_panel_discovery.py`
Read-only discovery of which skills, agents and MCP servers this project can actually reach —
project-local, user-global, installed plugins and this repo's own plugins tree — walking the
same places Claude Code itself looks, so the panel's composition pickers offer real building
blocks instead of free-typed names that may not exist. Front-matter parsing delegates to
`_help.front_matter` rather than reimplementing it. `panel-server.py` keeps thin aliases
(`discover = _panel_discovery.discover`, etc.) so its `/api/registry` route and existing
selftest fixtures keep working unchanged.

### `plugins/audit/scripts/_panel_settings.py`
Settings-shape knowledge moved out of `panel-server.py`: `FIELD_HELP`/`COMPOSITION_HELP`/
`SETTINGS_GROUPS` describe the whole Settings form once in Python rather than by hand (the
reason it exists — the `usage.*` block and most `tddReminder.*` keys had drifted out of a form
meant to make the config legible); `_META_KEYS`/`_META_API_ONLY`/`_META_FORM_KEYS`/
`_PHASE_KEYS`/`_TASK_KEYS` are the write path's security allow-list; `_settings_paths()`/
`_cfg_enums()` read the form's own bindings and the enum choices off `validate-config.py`
rather than a hand-kept copy. Sits at the bottom of the panel's import graph — must never
import `_help` or `panel-server`.

### `plugins/audit/scripts/_panel_state.py`
The panel's READ side, moved out of `panel-server.py`: given a project directory it reads the
config, the manifest (either layout), the usage ledger, the audit locks, the journal and the
capability policy, and returns the JSON payloads the UI renders (`build_state`, `areas_state`,
`policy_state`, `journal_state`, `usage_state`, `help_state`). Nothing here writes. It sits
above `_loader`/`_manifest_io`/`_help`/`_areas`/`_policy`/`_panel_settings`/`_panel_discovery`
and below `panel-server` — a selftest case asserts it never imports `panel-server` back.

### `plugins/audit/scripts/_panel_write.py`
The panel's WRITE side, moved out of `panel-server.py`: the whole path from a request body to
bytes on disk and a journal row — the write lock (`_acquire_write_lock`/`_release_write_lock`),
the change-preview machinery (`_flat_paths`, `_config_changes`, `_composition_changes`), and the
four writers (`write_config`, `apply_composition`, `write_policy`, `write_areas`). Sits above
`_panel_state` and below `panel-server`, forming the DAG `_panel_state -> _panel_write ->
panel-server`; a selftest case asserts it never imports `panel-server` back.

### `plugins/audit/scripts/_help.py`
The zero-token half of "what does this field mean" and "how does this actually work", backing
`/api/help` and the panel's help drawer. Field descriptions are extracted from
`schema/audit-config.schema.json`/`schema/audit-plan.schema.json` via `fields()`, never
restated by hand — a second copy of that prose is a second thing to drift, which this repo has
already shipped once. Topics are derived from the executable rule where one exists (the plan
gate's tiers from `_config.plan_gate_mode`, area resolution from `_areas`' own pinned sentences,
policy precedence from a worked `_policy.resolve` example) and are pointers, not restatements,
where the rule lives only in prose. `guide_card()` reads `agents/guide.md`'s frontmatter
so the panel cannot advertise a tool that agent does not hold.

### `plugins/audit/scripts/validate-config.py`
Structural validator for `.claude/audit.config.json`, dependency-free, mirroring `hooks/_config.py`
DEFAULTS. Complements `schema/audit-config.schema.json` with checks a schema pass doesn't surface
nicely (regex compilability of custom rules, positive thresholds) and hands the control panel a
machine-usable findings list. Permissive: unknown keys are WARNINGs, not findings. Exit 0 valid /
1 findings / 2 usage-or-unreadable. `--selftest`.

### `plugins/audit/schema/audit-plan.schema.json`
JSON Schema (draft 2020-12) for the manifest. Back-compatible: only `meta`/`phases` (and per-item
`id`/`title`/`status`) required; `additionalProperties: true` at object levels so a pre-existing
manifest validates unchanged after adding `$schema`. Enforces enums on `status`, `tests.mode`,
`risk`, review/finding `severity`. Encodes the **schema fixes**: documents the `tests.add`
tdd-vs-regression meaning + adds `expectRedFirst`; documents the `blockedBy` (hard gate) vs
`dependsOn` (intra-phase ordering) split; defines `finding` and `deferred.items` as
`string`-or-`object`; adds `task.maxAttempts`; documents that the orchestrator writes `outcome`;
adds `meta.buildCommands` so gate strings aren't hardcoded.
v0.2.0 adds the optional top-level `bugs[]` (`$defs/bug`, `$defs/bugStatus`: open | triaged |
in_progress | fixed | wontfix) and `task.bugId` — all optional, back-compatible.
v0.3.0 sets the canonical `$id`, adds the `^BUG-\d+$` pattern, and REMOVES the never-read
meta fields (`signOffChecklist`, `autoMode`, `modelPolicy`, `testPolicy`, `reviewPolicy`,
`skillsPolicy`, `statusLegend`, `phase.signOff`) — legacy manifests still validate
(`additionalProperties: true`; the structural validator accepts the legacy names silently).

### `plugins/audit/schema/audit-config.schema.json`
JSON Schema for the per-repo `.claude/audit.config.json`. The control panel validates edits
against it (alongside `validate-config.py`) before every atomic save, so a malformed config is
refused in the UI instead of silently dropping custom rules at hook time.

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

## 3. Finish & publish — DONE (v0.2.0), hardened (v0.3.0), release-quality (v0.4.0+)

All of the original TODOs are resolved: `plugin.json` author/homepage/license/repository
filled, `marketplace.json` owner + description filled (marketplace **name is
`quality-gates`** — the GitHub repo is named `claude-plugins`, the two intentionally
differ; see §2), starter `$schema` URL points at this repo, MIT `LICENSE` + `.gitignore`
added. Published at `https://github.com/AleksandarBisevac/claude-plugins`.
Releases follow `CONTRIBUTING.md`: one commit = version bump + CHANGELOG entry +
annotated `v<version>` tag; push `--follow-tags` only after CI is green.

The surface has grown since — all covered above and in `CHANGELOG.md`: the report renderer +
Azure DevOps `/audit:sync` (v0.5.0), pinned-tool agents + the PostToolUse shell-write guard
(v0.6.0), the split thin verb commands over `reference/orchestrator.md` (v0.7.0), and the
`/audit:panel` control panel — open/stop/status lifecycle (v0.13.x) and the compact,
collapsible, filterable Composition tab (v0.14.0).

## 4. Verify

CI (`.github/workflows/ci.yml`) runs 1–2 plus `claude plugin validate` on
ubuntu + windows for every push/PR. Locally:

```bash
# 1. Hooks + scripts pass their own selftests (every hook and script carries its own
#    selftest; CI sweeps the directories — stdlib only)
for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py; do
  python3 "$f" --selftest || exit 1
done
# launcher fails LOUD without an interpreter (permissionDecision "ask" JSON):
env PATH=/nonexistent /bin/sh plugins/audit/hooks/py-launch.sh guard-edits.py ask < /dev/null

# 2. Schema + validator accept the starter AND the dogfood manifest
python3 plugins/audit/scripts/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
python3 plugins/audit/scripts/validate-manifest.py docs/audit/audit-plan.json
npx ajv-cli validate --spec=draft2020 -s plugins/audit/schema/audit-plan.schema.json \
  -d plugins/audit/templates/audit-plan.starter.json
claude plugin validate . && claude plugin validate plugins/audit

# 3. IP scrub — must print nothing (substitute your source project's identifiers)
grep -riE '<client-name>|<internal-lib>|<bundle-id>' .

# 4. End-to-end in a throwaway repo
/plugin marketplace add /abs/path/to/claude-plugins
/plugin install audit@quality-gates
#   generate the manifest with /audit:init (or copy the templates), then:
/audit:status
#   edit a non-exempt file with no plan → require-plan denies; add #no-plan (or your
#   bypassKeyword) → armed + logged bypass, consumed only after a successful edit;
#   a custom rule blocks under its pathPrefix only; sed -i into a source file → denied;
#   edit a source file with no test touched → remind-tdd nudges (non-blocking);
#   interrupt a phase mid-run → /audit:resume picks up at the first commit-less task.
/audit:bug add "..." ; /audit:bug fix BUG-1 ; /audit:run BF1.1
```

## 5. How the pieces relate at runtime

**Creation**: `/audit:init` interviews you, fans out parallel read-only explorers, and
synthesizes the manifest; `/audit:task add` appends planned work; `/audit:bug add` records
bugs and `/audit:bug fix` materializes one into a red-first `tdd` task in a `BF<n>` phase.
Every mutation revalidates via `scripts/validate-manifest.py`.

**Execution**: the `/audit:*` verbs drive the manifest, spawning model-assigned subagents that load
`task.skills`, run `tests.gate`, and commit per task on a phase branch, then sign the phase
off (optional review skill + test gates + optional runtime boot) and ff-merge into
`meta.developmentBranch`. When a task carries `bugId`, its commit flips the linked bug to
`fixed` + `fixedIn`.

**Guard rails**: `detect-plan-skip` (on your prompt) arms a bypass → `require-plan` (on an
edit) consumes it or enforces the plan gate → `guard-edits` + `guard-secrets-read` block
token-logging/secret-reads → `remind-tdd` (after an edit) nudges toward test-first without
blocking. All project specifics come from `.claude/audit.config.json` (hooks) and `meta.*`
(commands).
