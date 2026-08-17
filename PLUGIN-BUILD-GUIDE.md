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
        _refs.py                          # every script path a document names, stat'd against the files on disk
        _usage_core.py                    # usage arithmetic: the price table, the hour bucket, the roll-ups
        _usage_analytics.py               # what the ledger MEANS: series, bands, budgets, routing, coverage
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
        _report_page.py                   # the report as a whole document: vocab, table, render_html
        _report_md.py                     # the report's Markdown twin (render_md), embedded in the page
        migrate-manifest.py               # /audit:migrate doer: single-file -> sharded (backup+restore)
        panel-server.py                   # localhost control-panel web UI (config + composition)
        _panel_ui.py                      # reads scripts/ui/panel.{html,css,js} at import, assembles UI_HTML
        _panel_page.py                    # the assembled page: the substitution chain -> UI_HTML + UI_TEMPLATE
        _panel_discovery.py               # discovers skills/agents/MCP servers this project can reach
        _panel_settings.py                # the Settings form's schema + the write-path key allow-lists
        _panel_state.py                   # the panel's READ side: everything GET /api/* answers with
        _panel_write.py                   # the panel's WRITE side: everything PUT /api/* actually does
        _help.py                          # zero-token self-description: schema field help + how-it-works topics
        gen-demo-manifest.py              # synthetic LARGE manifest fixture for demos/screenshots/CI
        gen-demo-usage.py                 # synthetic usage ledger fixture, consistent with a real manifest
        ui/                               # panel/report HTML+CSS+JS as real editor-highlightable files, no .py
        audit-journal.py                  # append-only hash-chained audit trail (append/verify/show)
      tests/                              # selftest blocks moved OUT of the modules they test (all 48)
        _harness.py                       # sys.path setup + the one check()/tally runner, was written 48 times
        test__cli_fmt.py                  # pilot 1: an importable helper
        test_migrate_manifest.py          # pilot 2: a hyphenated entry point (hyphen -> underscore)
        test_remind_tdd.py                # pilot 3: a hook (a test may import scripts/; the hook may not)
        test__areas.py                    # batch A: 13 more suites, same three shapes, one file each
        test__fmt.py                      #   (one test_<name>.py per migrated production file; see §2)
        test__loader.py
        test__manifest_io.py
        test__panel_ui.py
        test__policy.py
        test__report_md.py
        test__report_ui.py
        test__usage_core.py
        test_audit_lock.py
        test_gen_demo_manifest.py
        test_gen_demo_usage.py
        test_validate_config.py
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
  _refs -> _output
  _ui_theme -> _output
  _usage_core -> _output

L2:
  _panel_settings -> _loader, _output
  _panel_ui -> _output, _ui_theme
  _report_html -> _areas, _manifest_io, _output, _ui_theme
  _report_ui -> _output, _ui_theme
  _usage_analytics -> _output, _usage_core

L3:
  _help -> _areas, _loader, _output, _policy, _ui_theme
  usage_ledger -> _manifest_io, _output, _usage_analytics, _usage_core

L4:
  _panel_discovery -> _help, _manifest_io, _output
  _panel_page -> _loader, _output, _panel_settings, _panel_ui, _ui_theme
  _report_usage -> _fmt, _loader, _output, _report_html, _ui_theme

L5:
  _panel_state -> _areas, _help, _loader, _manifest_io, _output, _panel_discovery, _policy
  _report_md -> _output, _report_html, _report_usage

L6:
  _panel_write -> _areas, _manifest_io, _output, _panel_settings, _panel_state, _policy, _ui_theme
  _report_page -> _manifest_io, _output, _report_html, _report_md, _report_ui, _report_usage

L7:
  audit-doctor -> _cli_fmt, _loader, _output
  audit-journal -> _output
  audit-lock -> _output
  audit-status -> _areas, _cli_fmt, _fmt, _loader, _manifest_io, _output, _panel_discovery, _ui_theme
  audit-task -> _manifest_io, _output, _panel_write
  audit-usage -> _areas, _cli_fmt, _fmt, _loader, _output, _ui_theme
  gen-demo-manifest -> _loader, _output
  gen-demo-usage -> _loader, _output
  migrate-manifest -> _loader, _manifest_io, _output
  panel-server -> _manifest_io, _output, _panel_discovery, _panel_page, _panel_settings, _panel_state, _panel_write, _ui_theme
  render-report -> _loader, _manifest_io, _output, _report_html, _report_md, _report_page, _report_ui, _report_usage, _ui_theme
  validate-config -> _output, _policy
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

`find_script(filename)` is the hooks-side resolver: `filename` **anywhere** under
`../scripts`, recursively, by basename — the folders there are labels, not namespaces, and
a flat join is right only while the tree is flat. It is the third derivation of "where is
`scripts/`" and it is irreducible, because `hooks/` may import nothing from `scripts/` and
so cannot read `_output.SCRIPTS_DIR`; `tests/test__config.py`'s `fs1`–`fs5` hold it true by
READING both answers and comparing them, the way the pricing-table pair is held.
`hooks/meter-usage.py` calls it rather than keeping a second copy. Getting it wrong is the
most dangerous edit in this file: `_load_scripts_module` wraps its load in
`except Exception: return None` and every caller reads that as "the feature is not
installed", so a wrong path silently switches off the capability policy, the journal, the
ledger and the sharded-manifest read with every gate still green.

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

It is also **the anchor**, and that is why it is the one file that never moves.
`SCRIPTS_DIR`, `PLUGIN_ROOT`, `HOOKS_DIR`, `TESTS_DIR` and `REPO_ROOT` are the single
written-down statement of where the tree's directories are; seventeen sites used to derive
a parent from their own `__file__` and none does now. `script_files()` is `py_files()` over
`scripts/`, walked once per process and memoised (only for the default root, so a fixture
directory can neither poison nor read the cache). `install_path()` puts `scripts/` **and
every subdirectory of it holding a `.py`** on `sys.path`, front, root first, and **returns
the list it installed** — never None, never empty — so a caller can assert what happened
instead of trusting that an import worked. `scripts/ui/` drops out on its own because it
holds no `.py`, which turns an editorial rule into a mechanical one.

**`PATH_PREAMBLE` is the eleven lines every other `.py` under `scripts/` carries**, byte
for byte, after the stdlib imports and above the first sibling import. It walks UP until it
finds the directory containing `_output.py`, so it encodes no depth and terminates at the
filesystem root with a named `ImportError` rather than looping; then it imports `_output`
and calls `install_path()`. `path_preamble_violations()` COUNTS occurrences rather than
testing membership (a doubled preamble is as wrong as a missing one) and AST-checks that
`install_path()` runs above the first sibling import — a preamble below the imports it
exists to enable is decoration. `_output.py` is exempt by name, for two reasons: it *is*
the marker, and it holds `PATH_PREAMBLE` as a string, so a text count over its own source
would read as compliant.

The consequence worth stating out loud: **the folders under `scripts/` are labels, not
namespaces.** Everything stays in one flat name-space, `import` and `_loader.load_script()`
both resolve by bare basename, and basename uniqueness — enforced by
`_deps.layer_violations()` — is the load-bearing invariant. `depth_sensitive_paths()` is
what keeps it that way: no `.py` under `scripts/` may read `__file__` outside the pinned
preamble, except as `os.path.basename(__file__)`, which yields a name and not a location.
The rule is deliberately stronger than "no parent of `__file__`" — sixteen of the
seventeen old sites were written as a two-step (`_HERE = dirname(abspath(__file__))`, then
`dirname(_HERE)` far below), which any nesting-only rule waves through.

`--covered` writes through `write_lf_lines()` rather than `print()`. A machine-readable
list is not platform-dependent data: `print()` emits CRLF on Windows, CI's
`--covered | tr '\n' ' '` then leaves a `\r` glued to every path, its membership test
matches nothing, every migrated file gets run anyway, and the first one fails for printing
its "cases moved" pointer instead of the contract — green on ubuntu, red on windows, for a
defect in neither.

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

Resolution is **by basename at any depth**. `script_index()` is one
`{basename: [abspath, ...]}` map built lazily from `_output.script_files()` — the same walk
`install_path()` derives its `sys.path` directories from, so what can be loaded and what can be
imported are one fact rather than two that can drift. `script_path()` reads it and **raises
rather than guessing**, in three ways, each naming what it promises: a name that matches nothing
is an `ImportError` carrying the basename *and how many files were searched* (`among 0` is a
tree that was never walked, `among 41` is a typo, and a caller has to be able to tell those
apart); a name claimed by two files is an `ImportError` naming *both* paths; and a value
carrying a path separator is a `ValueError` naming *the value*, because silently dropping a
directory the caller spelled is how a caller comes to believe the directory mattered. There is
deliberately **no fallback** to `join(SCRIPTS_DIR, basename)` on a miss — that retry turns a
typo into a plausible-looking `FileNotFoundError` about a path nothing ever put a file at.
`load_script(basename)` is `load(script_path(basename))` and nothing else.

The collision refusal restates a rule `_deps.layer_violations()` already enforces, and the
duplication is deliberate: that lint fails the **build**, in a checkout; this one fails a
**run**, inside a consumer's installed plugin, where the lint has never executed. It is the one
failure the design could otherwise produce silently — the wrong module loaded under the right
name. `script_path` is deliberately **not** in `_deps._LOADER_FUNCS`: it resolves, it does not
load, so listing it would invent graph edges out of paths that are handed to `subprocess` or to
an `open()` (`render-report._bench_fixture` is the worked example).

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

### `plugins/audit/scripts/_refs.py`
The other half of the same idea, aimed at paths rather than at imports: roughly 150 places
spell a route to a `.py` under `plugins/audit/` — the command files, CI's own steps, this
guide, the plugin README, the schema descriptions, the worked example's shell scripts — and
until this module nothing stat'd any of them. `validate-manifest.py` compares `fileIndex`
against task `files` and never touches the filesystem; `guide_enumeration()` above matches by
BASENAME, so a `### ` heading survives the file moving into a subdirectory. `referenced_paths()`
returns EVERY match rather than only the broken ones, because the count is the check — a
pattern that quietly stops matching otherwise reports "0 missing", which reads like a clean
tree. Two matching modes: BARE in documents, and ANCHORED (`plugins/audit/`,
`${CLAUDE_PLUGIN_ROOT}/`, `$scripts/`) inside the plugin's own `.py`, which is what keeps
`guard-secrets-read.py`'s unanchored build-script literal — a fixture about a CONSUMER repo's
file — out of the scan while still catching `require-plan.py`'s three real lock-script
strings. `CHANGELOG.md` and `docs/design/` are excluded with the reason in the table: a path
that has since moved was true when it was written. `manifest_moved_files()` splits a MOVE
(loud: stale reference) from a DELETION (silent: correct history) by asking whether the
basename still exists anywhere in the plugin, and `sweep_glob_drift()` pins the six documents
that show the selftest sweep to the recursive `find` form — scoped to the runnable line, so
the two places this guide writes the flat glob as prose stay legal. This file is an anchored
surface itself, and its own fixture paths are BUILT rather than spelled for that reason.
`--selftest` (32 cases).

### `plugins/audit/scripts/_usage_core.py`
The arithmetic the whole metering stack stands on, and nothing else: the `DEFAULT_PRICING`
table plus `rates_for`/`price`, one ISO parser and one hour-bucket rule, and the roll-ups
(`totals`, `aggregate`, `aggregate_area`, `rows_for_area`, `heatmap`) the CLI, the report and
the panel all read. Values in, values out — no file, no process, no transcript — which is why
its 48 cases need no fixture directory. `pricing_divergences()` lives here too: `hooks/_config.py`
must price a model with no config present and may import nothing from `scripts/`, so its copy
of the 13 x 5 rate table is deliberate and the `pp` cases are what keep the two identical.
`--selftest`.

### `plugins/audit/scripts/_usage_analytics.py`
What the ledger MEANS, as `rows -> dict` functions: `series`, `compare`, `cache_profile`,
`unit_economics`, `cost_bands`/`band_of`, `phase_budgets`, `retry_cost`, `routing` (+ its
advice), `coverage` and `monthly_activity`. Every one of these is easy to compute and easy to
present dishonestly, so the guards live here rather than in each renderer — a projection is
suppressed below its sample gate, a cache profile reports rates and never a fabricated dollar
saving, routing advice compares only WITHIN a risk band and only on this repo's own evidence,
an absent phase budget renders as nothing rather than 0% or 100%. `COST_BAND_PARAMS` is the one
statement of the relative basis's shape; `panel-server.py` serialises that exact dict into the
page so `panel.js` cannot restate it differently. Depends on `_usage_core` and nothing else.
`--selftest`.

### `plugins/audit/scripts/usage_ledger.py`
The token-usage metering core `meter-usage.py` and `audit-usage.py --backfill` both call.
Claude Code hands hooks a `transcript_path`, not token counts, so this reads the transcript
JSONL directly — `message.usage` alongside `message.model`/`timestamp`/`gitBranch`/`sessionId`,
plus each subagent's sibling `subagents/agent-<id>.jsonl` + `.meta.json`. The one correctness
trap it exists to close: a single `message.usage` block repeats across every transcript entry
sharing a `message.id`, so naive summation overcounts spend by roughly 2.4x — this module dedups
by `message.id` within and across scans. Attribution runs task -> phase -> window ->
unattributed, highest precision first, nothing ever dropped. The two layers beneath it
(`_usage_core`, `_usage_analytics`) were split out when the file passed 2,600 lines, and every
public name they define is RE-EXPORTED here: nothing imports this module by name — every
consumer loads `usage_ledger.py` by path and reads attributes off the module object — so the
module object has to keep serving all of them, and the `rx` cases assert it does.

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
What is left in this file after the split is `main()` — argument parsing, the manifest
read, the theme resolve, the files it writes — plus `_verdict`, and the ~230 cases that
read a report `main()` actually wrote into a temp directory. Those cases pin the emitted
DOCUMENT (its markup, its emission order, the stylesheet, the embedded script), so they can
live nowhere else: a fragment module cannot render one. `--selftest` (includes XSS cases).

### `plugins/audit/scripts/_report_page.py`
The report as a whole document, moved out of `render-report.py`: the report's vocabulary
(`_plural`, the gate's condition labels, which optional columns a plan has earned), the
phase-row builder, and `render_html` itself — the function that glues `_report_html`'s
fragments and `_report_usage`'s section into one self-contained page, or (with
`fragment=True`) into the same page with no document wrapper, for a Claude Code Artifact
whose host supplies its own. Layer 6, and the reason is the gate: the verdict at the top of
the report is `audit-status.py`'s own word, and `audit-status` is an entry point at layer 7.
So `render_html` takes `verdict` as an INJECTED callable and `render-report.py` — which
already carries that L7 → L7 runtime edge, recorded in `_deps.KNOWN_LAYER_DEBT` — supplies
`_verdict`. Reaching the gate from here would be a helper calling up, and `_deps`'
layer lint reads runtime `_loader` calls, so it would report it. With no verdict supplied
the hero renders the "could not be evaluated" state the product already has for a gate that
raises: an honest unknown, never a fabricated Clear.

### `plugins/audit/scripts/_report_md.py`
The report's Markdown twin, `render_md`. It could not stay behind when `render_html` left:
the HTML page embeds this output base64-encoded as its "Download .md" payload, so
`_report_page` calls it — the single edge that makes the split two files rather than one
(`_report_page → _report_md → _report_html`/`_report_usage`, one way, no cycle). It escapes
only the Markdown metacharacters that would break a table (pipes, newlines) and passes raw
HTML through to whatever renders it; `render_html` is the hardened output for an untrusted
source. It also keeps the manifest's own machine vocabulary and the manifest's own phase
order, where the HTML segments and re-words: this table is read by GitHub and by `diff`, and
reordering it would change every diff against an earlier render for a presentational reason.

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
data, no whole-document assembly (that lives in `_report_page.render_html` /
`_report_md.render_md`, which call these dozens of times and glue the fragments together).
Every manifest value is untrusted JSON, so
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

### `plugins/audit/scripts/_panel_page.py`
The panel's assembled page, moved out of `panel-server.py`: the eight-substitution chain that
turns `_panel_ui.raw_template()` into what the browser gets, exporting the two names the server
imports — `UI_HTML` (the finished page wearing the default theme, which every page selftest
reads) and `UI_TEMPLATE` (the same page with the `/*__THEME_TOKENS__*/` marker intact, so
`do_GET` can dress it in the requesting project's theme per request). The order is load-bearing
and stated where it happens: the snapshot `UI_TEMPLATE = UI_HTML` sits *after* the last
substitution and *before* the theme one, and case `pg1` is what goes red if it moves. It also
holds the ~283 selftest cases that assert about the CSS and JavaScript in
`scripts/ui/panel.{css,js}` — three quarters of `panel-server.py` before the split, and claims
about the front end rather than about an HTTP server. Layer 4: it reaches `usage_ledger` (L3,
for `COST_BAND_PARAMS`), `_help` (L3, selftest only), `_panel_ui`/`_panel_settings` (L2) and
`_ui_theme`/`_loader` (L1), and never `_panel_state`, `_panel_write`, `_panel_discovery` or
`panel-server` — a selftest case asserts that.

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

### `plugins/audit/tests/` — ONE section, not one per file (v0.40.0, done)

45% of this tree (22,363 of 49,393 lines) was `--selftest` blocks living inside the modules
they test, and all 48 files carried their own copy of `check()`. Those blocks moved out, one
file at a time — three pilots, then batches A through E, then batch F: `_refs.py`, `_deps.py`
and `_output.py`, the three lints that own this boundary, migrating themselves with themselves.
**All 48 have moved**, `tests/test__output.py`'s `sc10`/`sc11` assert that end state by name,
and no production file carries a suite of its own. This section describes the whole
directory on purpose: §2 exists to answer
"what does this file decide", and a test file's answer is always "the cases of the file beside
it" — `_deps.guide_enumeration()` is scoped to `scripts/` + `hooks/` so that this stays one
section rather than becoming forty-eight.

**`_harness.py`** owns the two things a moved block cannot bring with it. *Path setup*, at
import time: `scripts/` and `hooks/` go on `sys.path`, derived from the harness's own location,
so a test file writes `import _output` or `import _config`. *The runner*: `run(body)` calls
`body(check)` and prints the `PASS`/`FAIL` lines and the `N/M cases passed` tally CI greps for.
It unified a measured vocabulary — 18 files took `check(label, cond)`, 18 took a third `detail`
argument, 22 called the first parameter `label` and 20 called it `name`, 39 printed `ALL PASS`
and 9 printed their own module name *with no failure sentinel at all* — into one shape:
`check(label, cond, detail="")`, detail rendered only on failure, `ALL PASS` / `SELFTEST
FAILED`. `run()` also puts the body in a `try`: nothing here prints until every case has run,
so an exception raised while computing a case argument used to take the whole suite's output
with it (measured: 0 `PASS` lines survived; through `run()`, 8 of 9 print and the escape is
reported as the failing ninth).

It also owns the two things a *source-reading* case cannot spell from `tests/`. **`module_source(mod)`**
replaces three identical `_src_of_this_file()` helpers (`panel-server.py`, `_panel_state.py`,
`_panel_write.py`) whose six call sites were all inside their own suites and none in the product:
moved literally, each would read the TEST file. **`between(text, start, end)`** replaces
`text.split(start)[1].split(end)[0]`, whose halves fail in opposite ways — a missing `start`
raises, a missing `end` *silently returns the rest of the file*. Measured on the real sources:
the panel's read-route slice widened from 4,011 to 16,507 characters and swallowed a write
route, and `_panel_state`'s `--name-only` **security** slice widened from 3,747 to 71,084 and
still "found" the flag. `between()` raises on either marker, and `run()` reports the escape as a
named failing case.

**Naming.** a production `x.py` becomes `tests/test_x.py`, with **hyphens becoming underscores**:
`migrate-manifest.py` → `test_migrate_manifest.py`, because a hyphenated name is not
importable and the entry points are hyphenated by convention. The rule lives in
`_output._test_name_for()` and nowhere else.

**The transformation is explicit.** The module under test is imported as `M` and its names
carry the prefix (`M.enabled(...)`). Not `globals().update(vars(mod))` — ruff selects `F`, and
a body of runtime-injected names is undefined-name noise waiting to happen. Not a
`from x import (a, b, c)` list either: two of the three shapes (a hyphenated entry point, a
hook) are unspellable in an `import` statement and must come through `_loader`, which returns a
module object. One style that works for all three, and `M.` says which side of the boundary a
name is on. **Case labels move byte-identical** — a changed label is a changed test, and the
migration proves the multiset before and after.

**What a move is NOT allowed to carry over literally.** Batch A (13 files) found three shapes
that mean something different once the code sits one directory over, batch B (8 files) added
two more, and batch C (the six panel files) added a sixth. Every one of them fails QUIETLY
rather than loudly if carried:

* `globals()["x"] = stub` — a suite that swaps a module global for a counting or mocking stub was
  rebinding a name in the module it lived in. From `tests/` it rebinds a name nothing calls, the
  production function keeps using the real one, and the counter reads 0. Write `M.x = stub`, and
  restore on `M` in the same `finally`. `test__usage_core.py`'s `ag` group is the worked example;
  the literal move was run and goes red with `got 0` on four cases. Batch B found three more
  (`test__usage_analytics.py`'s `bn4`, `test_usage_ledger.py`'s `_home`), and the `_home` one is
  the reason this is stated as *dangerous* rather than merely wrong: the real function stayed
  live, the ledger walk left the fixture, and the three `discover:` cases went looking in the
  developer's own `~/.claude/usage` — the exact escape they exist to forbid.
* `globals()` / `vars()` read for INTROSPECTION, not for rebinding — "which public names does
  this module define", "is this name served here". The subject is the module, so it is
  `vars(M)`, `hasattr(M, n)`, `M.__name__`. Carried literally these answer about the test file,
  which is empty of the thing being asked about: `usage_ledger`'s `rx1` reports all 40 re-exports
  missing (loud), while `_usage_analytics`' `bn5` reduces to `set() - _timed == set()` and
  `render-report`'s `bn6` to a clause that is true forever (both silent, both green).
  Batch E added the worst-behaved member of the family: `journal-writes`' `j4` read
  `getattr(sys.modules[__name__], "record_plugin_write", lambda *a: None)(...)`. From `tests/`
  `sys.modules[__name__]` is the TEST module, the `getattr` default hands back the lambda, the
  lambda returns `None`, and the case passes — measured PASS with the production function deleted.
  Name the subject **and drop the swallowing default**: `M.record_plugin_write(...)` raises
  `AttributeError`, which `run()` reports as a named failing case.
* `__file__` — meant "the module under test's source" (`_policy`'s `m3b` reads it to pin which
  `fnmatch` function is called) or "some real file with an mtime" (`audit-lock`'s `a-mtime`). The
  first must become `M.__file__`; the second may be anything, but should say which it is. A third
  reading turned up in batch B: `_report_usage`'s `u27` used it to mean "one of the files this
  source lint scans", where re-pointing it at `M.__file__` is correct but not sufficient — the
  set it belonged to was two files because two files existed when the rule was written, and the
  report is assembled by six now.
* a path built with `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` — `scripts/` and
  `tests/` are both one level under the plugin directory, so this resolves *correctly by
  coincidence*. Spell it off `_harness.SCRIPTS_DIR` / `_harness.HOOKS_DIR` so it stays correct.
  `_ui_theme`'s `ua1` is the variant that resolves *incorrectly* rather than by luck — it
  asserted `ui/` sits beside the module, which from `tests/` is simply false — and it is the case
  that shows the rule: say the same thing about the SUBJECT (`UI_DIR == SCRIPTS_DIR/ui`) rather
  than editing the assertion until it passes.
* a source SLICE spelled `src.split(start)[1].split(end)[0]` — batch C's addition, and the only
  one on this list that was already unsafe *before* the move. The two halves fail in opposite
  ways: a missing `start` raises, a missing `end` returns the whole remainder, so every
  `"x not in slice"` case over it passes by describing a region it never meant. Use
  `_harness.between()`, which raises on either. `_panel_state`'s `--name-only` case is the one
  that makes this a security rule rather than a tidiness one: a plain `git config --list` hands
  back credential helpers and tokens, and the vacuous form was measured passing over a
  71,084-character slice of a module whose real slice is 3,747.

**A moved case may have to become a better case.** Not licence to rewrite: labels move
byte-identical and the multiset is proven. But where the inline spelling depended on the suite's
location, re-pointing it is a real change and owes a red proof, and sometimes re-pointing alone
would preserve a scope that was itself accidental. `u27` is the worked example — a magnitude
planted in `_report_page.py` leaves the two-file form green and turns the six-file form red.

**A moved suite can retire an import edge.** `_deps` walks the whole AST, selftest included, so a
`_loader.load_script(...)` that only ever ran inside a suite is a real edge in the graph until the
suite moves — and then it is gone. Batch A retired two `KNOWN_LAYER_DEBT` entries this way
(`gen-demo-manifest` → `validate-config`, → `validate-manifest`) and shifted one line of the
generated module map (`validate-config` no longer imports `_loader`). Batch D retired a third
(`audit-doctor` → `gen-demo-manifest`, down to 17 entries) and shifted one more line of the map
(`_help` no longer imports `_panel_settings` — a *static* import that lived inside a case).
Both are the lints working: delete the retired entries deliberately, regenerate the fence with
`_deps.py --render`, and never add an entry to make a migration go green.

**Retirement is measured PER CALL SITE, not per module.** `audit-doctor` names five other entry
points besides `gen-demo-manifest`, and each one's `_load(...)` sites have to be classified by
AST before an entry can be deleted: `audit-journal` and `audit-lock` are loaded from *both* the
checks and the suite, so their entries stay. A whole-file grep would have retired three.

**`hooks/` cannot retire a debt entry at all, and batch E is where that became worth saying.**
Three loader names left the hooks' ASTs with their suites (`guard-bash-writes` dropped
`_config._load_journal_lib`, `_config._load_lock_lib` and an `importlib` load of
`journal-writes.py`; `require-plan` dropped `_config._load_lock_lib`; `_config` dropped the only
in-file call of its own `policy_mod`). None was an edge: `_deps` scans `hooks/` **only** for the
static hooks→scripts import ban, never as graph nodes, and each of those loads physically lives in
`_config.py`, which keeps it and still serves it to production through `manifest_lock_conflict()`
and `guard-capabilities`. `KNOWN_LAYER_DEBT` stayed at 17 and the generated module map did not move.

**Batch F retired nothing either, and the reason is worth one line: none of the three lints
makes a `_loader` call at all.** Their only sibling edges are static `import _output`
(`_refs.py` once, in `__main__`; `_deps.py` twice, at module level and in `__main__`), and all
three call sites are production. `KNOWN_LAYER_DEBT` is still 17 and `_deps.py --render` is
byte-identical across the batch — which the fence below required rather than merely allowed.

**A lint that scans the tree it lives in must not plant its own needle there, and batch F paid
that three times.** `_refs.py` had already learned it: its fixture paths are BUILT from
`PLUGIN_REL` because an anchor spelled beside a `scripts/…py` is a real reference to a file that
exists for four milliseconds, and `c5` reports it — the constants moved to `tests/` with the
cases, since `tests/` is an anchored surface too. `_output.py` hit the same class twice on its
own first run and came back classified `both`: `_CONTRACT = "cases passed"` IS a string constant
carrying the contract, and two of its function docstrings spell the contract while explaining
what it is. Both are fixed at the source rather than exempted — the constant is assembled from
two tokens, and the proxy now drops every docstring (any `ast.Expr` holding a string, at any
depth) instead of only `tree.body[0]`. A `print(...)` argument is not a statement, so a real
inline suite is still seen.

**The rule stopped being permissive when it ran out of things to permit.** `inline` was the
clean half of an OR while the migration ran; with 0 inline and 48 covered it is now a DEFECT
class beside `both` and `neither`, so a file that ships a new inline suite is named rather than
accepted. `selftest_coverage()` answers that in one place — a `defects` list, every offending
name tagged with its class — instead of each caller re-spelling which keys count. Proven red
by giving the real tree a throwaway production file with an inline suite and no test file: the
old predicate passed, the new one failed with one `inline` entry naming that file, and `sc10`
printed it. (The probe's path is described here rather than written: this document is one of
`_refs`' BARE surfaces, and spelling a `scripts/` path that no longer exists is a missing
reference `c5` reports — which is how this paragraph was caught the first time it was written.)

**What the boundary lints say.** `_output.selftest_coverage()` classifies every production
file as `inline` / `covered` / `both` / `neither` (plus orphan and colliding test files), and
`tests/test__output.py` asserts the counts — because a rule with an OR in it (`inline or
covered`) is exactly the shape that lets a file with NEITHER through. `covered` is now the only
clean class; `inline`, `both` and `neither` are all defects, and all of them reach the `defects`
list a caller asserts on. CI's sweep takes its skip list from `_output.py --covered`,
the same function, so it cannot skip a file nobody is testing. `_deps.tests_import_violations()`
holds the other direction: nothing under `scripts/` or `hooks/` may import from `tests/`, so the
test tree stays deletable. `tests/` is deliberately absent from `_deps.LAYERS` (a test file has
no position in the product's import order) but IS in scope for `_output.house_style_violations()`
and `entries_missing_guard()` — the 3.8 dialect and the `safe_stdio()` guard apply to a test
exactly as they apply to a script.

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
#    selftest; CI sweeps the directories — stdlib only). `find`, not `*.py`: a glob
#    stops at the top level, so a file one directory down is silently never run and
#    the sweep still exits 0 — a green build over a partial tree.
for f in $(find plugins/audit/hooks plugins/audit/scripts -name '*.py' | sort); do
  python3 "$f" --selftest || exit 1
done
# ...plus the suites that have moved out into tests/ (see §2). A migrated file still
# exits 0 on --selftest, so the loop above stays green over a suite it no longer runs.
for f in $(find plugins/audit/tests -name '*.py' | sort); do
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
