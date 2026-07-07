# Plugin build & handoff guide

This repository is a **standalone Claude Code plugin** that packages a manifest-driven
`/audit` fix-pipeline plus six guard hooks and three pinned-tool agents. It was extracted (de-coupled, IP-scrubbed)
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
        sync.md                           # /audit:sync — Azure DevOps work-item sync
      agents/
        audit-explorer.md                 # mechanically read-only auditor (no Edit/Write/Bash)
        audit-executor.md                 # task executor (no web tools, no nested agents)
        audit-reviewer.md                 # sign-off reviewer (no edit tools)
      hooks/
        hooks.json                        # wires the 6 hooks to events (${CLAUDE_PLUGIN_ROOT})
        py-launch.sh                      # interpreter launcher: python3→python→py, fail-loud guards
        _config.py                        # shared config loader + path/manifest helpers
        require-plan.py                   # plan-first enforcement (Pre observes, Post commits state)
        detect-plan-skip.py               # arms the plan-first bypass + config-error warning + state GC
        guard-secrets-read.py             # blocks secret reads (direct+indirect) + shell source writes
        guard-edits.py                    # token-logging ban, custom rules, self-edit/forgery block
        guard-bash-writes.py              # PostToolUse git-status diff check (unplanned shell writes)
        remind-tdd.py                     # non-blocking TDD nudge (PostToolUse)
      reference/
        manifest-conventions.md           # shared command conventions (ids, templates, revalidate)
      schema/audit-plan.schema.json       # JSON Schema (draft 2020-12) for the manifest
      scripts/
        validate-manifest.py              # dependency-free referential validator (cycles, links)
        audit-status.py                   # headless rollup + CI gate (--json/--gate)
        render-report.py                  # self-contained HTML+MD report (CI artifact)
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
`allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion` — values are
QUOTED strings; an unquoted description containing `: ` silently drops ALL frontmatter).
Logic preserved from the original: readiness rule, branch-per-phase, per-task subagent spawn
with model+skills, TDD/regression/gate-only discipline, per-task commit, phase sign-off,
an invocable `resume` subcommand, reporting — plus the 0.3.0 guards: preflight
(config/manifest/usage), `run` status guards, infra-vs-test failure split, unconditional
high-risk confirmation, `--no-ff` fallback when ff-merge fails, `desiredOutcome` wiring.
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
- PostToolUse `Edit|Write|MultiEdit|NotebookEdit` → `require-plan.py` (state commit), `remind-tdd.py`, `guard-bash-writes.py` (records tool edits; all **open**)
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
Each hook does `sys.path.insert(0, dirname(__file__)); import _config`. `--selftest` (6 cases).

### `plugins/audit/hooks/require-plan.py`
Plan-first gate on Edit/Write/MultiEdit/NotebookEdit, registered under BOTH PreToolUse and
PostToolUse. ALLOW/BLOCK order: unknown tool/no path → allow; exempt glob (config) → allow;
file covered by an `in_progress` manifest task → allow; single-use bypass armed → allow;
else first small (change **magnitude** = max(added lines, chars/200, removed lines)
`<= trivialLineThreshold`) non-exempt file per session → allow, a 2nd distinct file or an
over-threshold change → **deny** (canonical `permissionDecision` JSON) with guidance.
**Transactional state**: PreToolUse only observes (the edit may still be denied by a sibling
hook or the user); PostToolUse — which fires only after a successful edit — consumes the
bypass (logged) and records the free-file slot. All tunables from config (`manifestPath`,
`exemptGlobs`, `trivialLineThreshold`, `stateDir`, `logsDir`, `bypassKeyword`).
`--selftest` (22 cases).

### `plugins/audit/hooks/detect-plan-skip.py`
UserPromptSubmit logger. If the prompt contains `bypassKeyword` (config; default `#no-plan`),
writes `stateDir/plan-bypass-<session>.json`, appends to `logsDir/plan-bypass.log`, and tells
the user (systemMessage) the bypass is live. Also surfaces `_configError` (malformed config)
once per session, and opportunistically garbage-collects session state files older than 7
days (incl. forgotten armed bypasses). Never blocks. `require-plan.py`'s PostToolUse pass
consumes (deletes) the bypass file after the next non-trivial edit actually happens —
single-use. `--selftest` (4 cases).

### `plugins/audit/hooks/guard-bash-writes.py` (v0.6.0)
PostToolUse watcher — the "complete control" for shell writes the PreToolUse text
inspection cannot decide (upstream #29709). Edit-tool events RECORD the touched file;
Bash events diff `git status --porcelain -uall` against the session's last-seen dirty set:
a NEW dirty source file that is not exempt, not the manifest/lock, not tool-edited, and not
covered by an `in_progress` task triggers a non-blocking `additionalContext` warning (once
per file per session). Needs a git repo; git errors/timeouts (5 s) are silent. Config:
`bashWriteCheck.enabled` (default true). `--selftest` (13 cases incl. a real `git init`
integration case).

### `plugins/audit/agents/` (v0.6.0)
Three pinned-tool agents the commands spawn via `subagent_type` (with a general-subagent
fallback for older Claude Code): `audit-explorer` (Glob/Grep/Read — mechanically read-only;
/audit:init fan-out), `audit-executor` (Read/Edit/Write/Glob/Grep/Bash/Skill — no web tools,
no nested agents; task execution and review fixes), `audit-reviewer`
(Read/Glob/Grep/Bash/Skill — no edit tools; sign-off review runs the project review skill
inside the agent so the diff stays out of the orchestrator's context). Tool lists are a hard
boundary that does not depend on subagent hook inheritance (#43772); the agent system
prompts carry the invariants (no commits, no stash, red-first discipline, JSON return
shapes) while spawn prompts add the per-task specifics.

### `plugins/audit/hooks/guard-secrets-read.py`
Read/Grep/Bash secret backstop. Blocks: reading secret file *contents* (`.env`, `credentials*`,
`.p12/.mobileprovision/.keystore/.jks/.p8/.pem`) via the Read tool, via Grep path/glob (Grep
prints file lines), via shell read-verbs — including the indirect ones (`git show`/`cat-file`,
`source`/dot-source, and `cp`/`mv`/`rsync`/`install` relocating a secret) — and via inline-eval
one-liners (`python -c`, `node -e`, …); also blocks `printenv`/`env` dumps and echoing
token-like vars. Plan-first backstop for Bash writes: inline-eval writes AND the high-signal
shell write forms (`sed -i`, `tee`, `>`/`>>` redirects — heredoc redirects included) into
non-exempt source files not covered by an `in_progress` task (source extensions derive from
`tddReminder.sourceGlobs`). Listing NAMES stays allowed. `secretPatterns.extra` (config) adds
patterns. `--selftest` (49 cases) uses fictional paths only.

### `plugins/audit/hooks/guard-edits.py`
Edit/Write/MultiEdit/NotebookEdit content guard. (1) Path-based protection first: denies edits
of the INSTALLED plugin's own files (self-edit; dev-checkout exempt) and writes to
`plan-bypass-*` state files (bypass forgery). (2) `guardEdits.customRules` (config) — each
`{pathPrefix, bannedPattern, message}` blocks its regex under its path prefix; ships EMPTY (the
one-library listener rule that used to be hardcoded is now just an example in the config
template). (3) Token-logging ban built dynamically from `guardEdits.tokenVars` — blocks
`console.*`/`Sentry.*`/`remoteLog(… token …)` and `Bearer ${token}`, allowing `.slice` prefix
debug. `--selftest` builds its token test-input at runtime (`"access"+"Token"`) so this source
file itself never trips a token-logging guard (13 cases).

### `plugins/audit/hooks/remind-tdd.py`
PostToolUse (Edit|Write|MultiEdit|NotebookEdit) **non-blocking** TDD nudge: when a SOURCE file changes and
no TEST file was touched this session, prints `hookSpecificOutput.additionalContext` (exit 0 —
never blocks; PostToolUse is the only event with a first-class non-blocking Claude-visible
channel). Records test-file touches BEFORE any warn logic (the hook watches its own Edit
stream — that ordering is the whole mechanism). Throttled (once per file + global
`throttleMinutes` gap) and manifest-aware: silent when the file is covered by an
`in_progress` `gate-only` task (`inProgressPolicy`: skip-gate-only | skip-all | warn-always).
All tunables under config `tddReminder`. `--selftest` (13 cases).

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
Exit 0 clean (warnings allowed) / 1 findings / 2 usage-or-unreadable. `--selftest` (33 cases).

### `plugins/audit/scripts/audit-status.py` (v0.5.0)
Headless rollup + CI gate, stdlib-only; imports validate-manifest.py as a library via
importlib. `--json` prints the machine-readable summary (phases done/total, tasks/bugs by
status, ready-task list mirroring /audit's readiness rule); `--gate` exits 1 on tripped
conditions — default `invalid,open-high-bugs,blocked-tasks`, tunable with `--fail-on`
(also `open-bugs`, `in-progress` for release freezes). Exit 0/1/2. `--selftest` (14 cases).

### `plugins/audit/scripts/render-report.py` (v0.5.0)
Manifest → self-contained `audit-report.html` + `.md` (inline CSS, zero network fetches):
phase progress bars, task tables, bug rollup, ADO links. Consumes audit-status's rollup
(single source of truth). Every manifest string is HTML-escaped — manifest content is
untrusted — and only http(s) URLs render as links (`javascript:` degrades to text).
`--selftest` (13 cases, incl. XSS cases).

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

## 3. Finish & publish — DONE (v0.2.0), hardened (v0.3.0), release-quality (v0.4.0)

All of the original TODOs are resolved: `plugin.json` author/homepage/license/repository
filled, `marketplace.json` owner + description filled (marketplace **name is
`quality-gates`** — the GitHub repo is named `claude-plugins`, the two intentionally
differ; see §2), starter `$schema` URL points at this repo, MIT `LICENSE` + `.gitignore`
added. Published at `https://github.com/AleksandarBisevac/claude-plugins`.
Releases follow `CONTRIBUTING.md`: one commit = version bump + CHANGELOG entry +
annotated `v<version>` tag; push `--follow-tags` only after CI is green.

## 4. Verify

CI (`.github/workflows/ci.yml`) runs 1–2 plus `claude plugin validate` on
ubuntu + windows for every push/PR. Locally:

```bash
# 1. Hooks + scripts pass their own selftests (all ten, stdlib only)
for f in plugins/audit/hooks/_config.py \
         plugins/audit/hooks/require-plan.py \
         plugins/audit/hooks/detect-plan-skip.py \
         plugins/audit/hooks/guard-edits.py \
         plugins/audit/hooks/guard-secrets-read.py \
         plugins/audit/hooks/guard-bash-writes.py \
         plugins/audit/hooks/remind-tdd.py \
         plugins/audit/scripts/validate-manifest.py \
         plugins/audit/scripts/audit-status.py \
         plugins/audit/scripts/render-report.py; do
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
/audit status
#   edit a non-exempt file with no plan → require-plan denies; add #no-plan (or your
#   bypassKeyword) → armed + logged bypass, consumed only after a successful edit;
#   a custom rule blocks under its pathPrefix only; sed -i into a source file → denied;
#   edit a source file with no test touched → remind-tdd nudges (non-blocking);
#   interrupt a phase mid-run → /audit resume picks up at the first commit-less task.
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
