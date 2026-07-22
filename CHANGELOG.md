# Changelog

All notable changes to the `quality-gates` marketplace and its `audit` plugin.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the
`audit` plugin's `plugin.json` version, tagged `v<version>` on this repo.

## [Unreleased]

### Added
- **`/audit:panel` — a local control panel for config + composition.** An ephemeral,
  on-demand Python-stdlib server (Ctrl-C to stop; not a running service) serves a
  themeable browser UI (the report's Slate & Teal system, light/dark, responsive)
  to visually manage the plugin:
  - **Guards & paths** — a form over `.claude/audit.config.json`, now backed by a
    JSON schema (`schema/audit-config.schema.json`) + a `validate-config.py`
    validator; edits are validated before an atomic write.
  - **Composition** — set `meta.reviewSkill`, per-task `skills`/`model`, per-phase
    `review.model`, and `meta.buildCommands`, with pickers **populated by discovery**
    of the skills & agents actually available (project `.claude/`, `~/.claude/`, and
    installed plugins) plus the MCP servers in scope. Writes back only these
    composition fields — never structural CRUD — validated via `validate-manifest.py`.
  - **Overview** — the live rollup + validation status.
  Safety: binds `127.0.0.1` only + a per-launch token on every API call, refuses
  writes that escape the project dir, and refuses manifest writes while
  `<manifestPath>.lock` is held. New: `commands/panel.md`, `scripts/panel-server.py`,
  `scripts/validate-config.py`, `schema/audit-config.schema.json`. The shareable
  report is unchanged (still self-contained / zero network fetch).

## [0.12.0] - 2026-07-16

A visual/UX overhaul of the HTML report: a modern, themeable, responsive design
built on CSS tokens — light + dark, a pipeline-rail signature, refined components,
and tasteful motion — with every interaction and invariant of the previous report
preserved (one self-contained file, zero network fetches, escaped, print-safe).

### Changed
- **Report redesign — a modern, themeable visual system.** The HTML report moves
  onto CSS design tokens (a "Slate & Teal" palette) with **light + dark themes**:
  it follows the OS by default and adds a toolbar toggle that persists. The phases
  table gains a **pipeline rail** — a continuous status-colored spine with a node
  per phase and per-task rail segments — as its signature, plus soft cards for the
  overall/summary bands, pill buttons + a primary Save-as-PDF action, refined
  status/risk chips, a monospace tabular data-face for ids/SHAs/dates, an animated
  progress fill, and toolbar elevation on scroll. Tasteful motion throughout,
  gated by `prefers-reduced-motion`; still one self-contained file, **zero network
  fetches** (system fonts only), fully escaped, keyboard-navigable, **responsive**
  (on phones/tablets the wide tables scroll inside their own frame instead of the
  page), and print/PDF renders on a light A4 sheet regardless of theme. Verified in a browser (light +
  dark, all interactions, reduced-motion). Status/risk colors moved from inline
  styles into theme tokens keyed off `data-status`/`data-risk`.

## [0.11.0] - 2026-07-16

Turned the report into a shareable, scalable artifact and gave the plugin a real
front door. The HTML report is now one collapsible, filterable table that scales
to 40+ phases, prints to PDF, and can carry an AI summary; a curated
`examples/acme-store/` audit + a GitHub Pages demo + README quickstart/screenshots
let people see what the plugin does without installing it.

### Changed
- **Interactive report scales to large audits.** The HTML report is now one
  collapsible table: each phase is a group-row (status chip, progress bar,
  desired outcome) that expands to its task rows on click; phases are **collapsed
  by default**, so a 40-phase / 200-task audit opens as ~40 scannable rows
  instead of one endless scroll. Filtering is split by level: the toolbar holds a
  **phase** text search and **phase-status** chips, both *visually removing*
  non-matching phases; a **task-status** filter is **contextual** — it appears
  inside each phase when expanded and filters only that phase's tasks (filtering
  one phase never touches another). Text search auto-expands matching phases;
  sort is per-phase (tasks stay grouped); **expand-all / collapse-all persists**
  across filtering and page reload (localStorage); the page gains a `<title>`
  (browser-tab name). Still one self-contained file, zero network fetches, every
  value escaped, and fully readable with JS off (rows render expanded; JS
  collapses them). Verified in a browser against a synthetic 40×5 report.
- **Report readability: completion dates + status coloring.** The task table gains
  a sortable **done** column (completion date; the full started/completed
  timestamps show on hover; in-progress tasks show their start date). Risk is now
  a tinted chip (low/med/high = green/amber/red, distinct from the solid status
  chips), and every task and phase row carries a **status-colored left edge**
  (green/amber/red/grey) so state reads at a glance. The Markdown twin gains the
  matching `done` column.

### Added
- **Report: PDF, an AI summary, and a Markdown download.** A **Save as PDF**
  button prints the report on **A4 with every phase expanded** (via the browser
  print dialog + a print stylesheet — no bundled PDF library, so the file stays
  small and self-contained). A **Summary** box shows an AI-authored narrative
  when present — `/audit:report` composes 2–4 sentences and passes them via a new
  `render-report.py --summary-file PATH` (or a manifest `meta.reportSummary`);
  the file is injected in-memory, so the command stays read-only. A **Download
  .md** button saves the Markdown twin (embedded as base64) even from a
  standalone HTML. The quantitative "Overall" line remains the always-present
  fallback. Verified end-to-end in a browser.
- **Onboarding: a worked example, a live demo, and quickstart docs.** New
  `examples/acme-store/` — a small, schema-valid manifest that covers every
  phase/task status, a blocked task, cross-task deps, a hard phase gate, the full
  bug lifecycle (open→triaged→in_progress→fixed→wontfix), a reciprocal bug↔task
  link, and an ADO link — plus its generated report. CI validates it on every
  push. A GitHub Pages demo (`docs/index.html` = the example report;
  `docs/demo-large.html` = a 40×5 report) gives a click-through live link, and the
  READMEs gain a Quickstart, screenshots, and a per-field **`meta` reference**
  table + a **Reports** section.
- **`meta.reportBasename` / `render-report.py --basename`** — custom report
  filenames (e.g. `q3-audit` → `q3-audit.html/.md`; default `audit-report`),
  sanitized to `[A-Za-z0-9-_]`. The **Download .md** button uses the same name.
  Both `reportBasename` and `reportSummary` are now first-class `meta` keys
  (schema + validator).

### Fixed
- **Validator now flags a `done` phase that still has non-done tasks.** A phase
  is `done` only after sign-off (every task done); `validate-manifest` never
  checked that invariant, so a stale-status slip passed silently. Added the
  check + a regression selftest, and corrected the dogfood roadmap manifest's
  **P3** — its four tasks carried commits + outcomes (the work shipped in
  v0.5.0) but were still marked `pending` from a hand-regeneration. Surfaced by
  the interactive report showing P3 as `done` with a `0/4` progress bar.

## [0.10.0] - 2026-07-16

A self gap-audit of the whole plugin (trust core, guards, command surface,
packaging) drove a round of hardening plus one feature. Deliberately-accepted
trade-offs documented in `SECURITY.md` (fail-open on internal error, `cp`/`mv`
Bash-write coverage, name-based secret matching) were left as-is by design.
Every fix carries a regression selftest (suites now: `_config` 6, `guard-edits`
16, `guard-secrets-read` 58, `require-plan` 25, `remind-tdd` 13,
`guard-bash-writes` 14, `detect-plan-skip` 4, `validate-manifest` 41,
`audit-status` 33, `render-report` 20).

### Added
- **Interactive HTML report** — the report tables now support a text filter,
  click-to-sort columns (natural order, so `P2` before `P10`), and per-status
  quick-filter chips. Inline, self-contained JavaScript: no server, zero network
  fetches, still one shareable file / CI artifact. Progressive enhancement (fully
  readable with JS off); the untrusted manifest still cannot inject (every value
  HTML-escaped; script touches only `textContent`/attributes). Verified
  end-to-end in a browser.

### Fixed
- **CI gate false-negative on the worst bugs.** `open-high-bugs` counted only the
  literal severity `"high"`, so an open `critical`/`blocker`/`sev1`/`p0` bug
  passed the merge gate. It now matches a normalised high-or-worse vocabulary.
- **Crash on a malformed manifest.** A non-object JSON root (`null`/`[]`/scalar)
  raised an uncaught `AttributeError` in `audit-status`/`render-report`; both now
  exit 2 cleanly, and `validate-manifest` upholds its "never raises on arbitrary
  JSON" contract (non-list/unhashable `blockedBy`/`dependsOn`/`fileIndex`/`tasks`
  become findings; boolean `version` rejected).
- **Manifest concurrency lock now covers `init`/`task`/`bug`/`sync`** (previously
  only the execution verbs locked). `/audit:init` regenerate can no longer clobber
  an in-flight run; the quick-mutation commands hold the lock around writes.
- **Re-opening a `done` bugfix task** now also reopens its linked bug instead of
  leaving `bugs[]` marked `fixed` at a stale SHA.
- `/audit:sync` `allowed-tools` now grants the `mcp__azure-devops__wit_*` tools
  its body tells the model to use; `/audit:status` reads the ready-now list from
  `audit-status.py` (one implementation of the readiness rule, no drift);
  `review`/`resume` emit progress output like their siblings.
- `render-report` HTML now carries `<!doctype>`/charset (standalone render, not
  quirks mode); the `.md` twin documents that it relies on the renderer to
  sanitise HTML.

### Security
- **`guard-secrets-read`** now blocks SSH private keys
  (`id_rsa`/`id_dsa`/`id_ecdsa`/`id_ed25519`), bare `~/.aws/credentials` read via
  Bash, and `.pfx`; the shell-write backstop also catches `1>`/`>|` redirects.
- **`guard-edits`** token-logging ban now catches a token as the sole/first
  argument (`console.log(accessToken)`) and via property access
  (`this.accessToken`) — previously only later args / interpolations were caught.

### Docs
- Marketplace/plugin descriptions no longer advertise a removed bare `/audit`
  command and now list `/audit:sync`; "five hooks" → "six" in SECURITY/README;
  residual space-form commands fixed; Python floor notes CI verifies 3.12;
  build-guide selftest tallies and guard coverage refreshed.

## [0.9.0] - 2026-07-15

Made the audit's compute choices deliberate and reproducible instead of
inherited from the calling session: reasoning effort is now pinned per agent,
and the task model floor is raised to `sonnet`.

### Changed
- **Reasoning effort is pinned per agent, no longer inherited from the calling
  session.** Each audit agent sets `effort` in its own definition:
  `audit-reviewer` → `high` (sign-off analysis, once per phase), `audit-executor`
  and `audit-explorer` → `medium`. Previously effort silently rode on whatever
  the invoking session ran at — a `max`-effort session made every executor run at
  `max` (observed: ~360k tokens on a single review-fix task) — so an audit's
  cost/latency was not reproducible. The `Agent` tool has no per-spawn effort
  override, so the definition frontmatter is the only lever; `orchestrator.md` now
  states the spawn passes **only** `model`, never effort (and that the
  general-purpose fallback reverts to session effort — an accepted degradation).
- **Task model floor raised to `sonnet`; `haiku` is no longer assigned to fix
  work.** `/audit:init` synthesis and `/audit:task` now default to `sonnet` for
  all low/med-risk work (mechanical included) and escalate to `opus` for
  `risk: "high"`. A botched `haiku` attempt burns retries plus a reviewer round,
  costing more than one clean `sonnet` pass. The `risk:"high"` → never-`haiku`
  guard in `orchestrator.md`/schema stays as defense for hand-written manifests.
  This is a creation-time rule — existing manifests with `haiku` tasks are not
  auto-upgraded.

## [0.8.0] - 2026-07-09

Live-validated the orchestrator for the first time, then made a long run legible
and previewable.

### Fixed
- **Gate commands broke on git-in-a-subdir manifests** (found by the first real
  end-to-end run). 0.7.0 told the orchestrator to run gates "from the git root";
  0.2.0-generated manifests carry `cd <gitRoot> && …` in `buildCommands` and
  expect the project dir. Now: **git** runs via `git -C <gitRoot>`, **gate
  commands run from the project dir verbatim** (the manifest carries any needed
  `cd`), and `/audit:init` prefixes `cd <gitRoot> && ` when the workspace is a
  subdir. `orchestrator.md`, `init.md`, README updated.
- A subagent that returns no usable result (died / no parseable outcome / no
  file change) is now explicitly a failure → retry to `maxAttempts` → `blocked`
  (previously implicit).

### Added
- **Progress output** — the execution verbs emit a short line as each step
  happens (phase entry, per-task start/result/commit, each sign-off gate, merge)
  so a long `/audit:phase` is legible instead of silent until the end.
- **`--dry-run`** on `/audit:next`, `/audit:run`, `/audit:phase` — read-only
  preview of the plan (branch, ready tasks, parallel groups, gates, merge target)
  with nothing created, spawned, or committed.
- **Richer `/audit:report`** — an overall progress header (tasks/phases/bugs/
  ready), per-phase branch + merged-at, and a per-task outcome column; still
  self-contained and fully escaped. 16 selftest cases.
- **Readability** — README TL;DR quickstart at top, an "At a glance" summary in
  `orchestrator.md`, and scannable `[x]/[~]/[!]/[ ]` status markers + an overall
  line in `/audit:status`.

### Validation
First real end-to-end `/audit:phase` run against a live repo (throwaway Nx
monorepo, git in `test/`, nothing pushed): preflight → phase branch → parallel
subagents → real lint gate → per-task commits (gitRoot prefix stripped, clean
hygiene) → sign-off → ff-merge, then full restore. Confirmed the 0.6.1 gitRoot
fix and the lock/preflight work in a live run; surfaced the gate-cd bug fixed
above.

## [0.7.0] - 2026-07-08

Command surface: split the orchestrator into `/audit:<verb>` commands
(no more `/audit:audit`).

### Changed
- **The single orchestrator command is gone.** Because Claude Code namespaces
  plugin commands as `/<plugin>:<command>`, the old `audit.md` was only
  reachable as the awkward `/audit:audit` (and bare `/audit` — which every doc
  and the plugin's own recap text wrongly suggested — is not a command at all,
  producing "Unknown command: /audit"). Each action is now its own verb command:
  - `/audit:status` · `/audit:next` · `/audit:run <id>` · `/audit:phase <id>` ·
    `/audit:review <id>` · `/audit:resume` · `/audit:report`
  - consistent with the existing `/audit:init` · `/audit:task` · `/audit:bug` ·
    `/audit:sync`.
- Shared execution logic (config resolution, preflight incl. git-root/submodule/
  lock, guardrails, readiness, branch-per-phase, Execute-the-task, Phase sign-off,
  resume, reporting) moved to **`reference/orchestrator.md`**, which every verb
  command reads; each verb file is thin (its slice + a pointer to the reference).
- **All handoff/recap text and docs now emit `/audit:<verb>`** — previously the
  commands' own output told users to run `/audit run …`, `/audit phase …`, etc.,
  which don't exist, so copy-pasting them failed. Fixed in the command bodies,
  README, PLUGIN-BUILD-GUIDE, schema descriptions, and hook comments.

### Migration
No manifest changes. If you used `/audit:audit <sub>` (or tried bare `/audit`),
switch to the matching verb: `/audit:audit status` → `/audit:status`,
`/audit:audit run X` → `/audit:run X`, `/audit:audit phase P0` → `/audit:phase P0`.
After updating, `/reload-plugins` (or restart) so the session picks up the new
command set.

## [0.6.2] - 2026-07-07

Submodule preflight guard.

### Added
- **Git-submodule detection.** The orchestrator commits from one repo (the git
  root); files inside a submodule belong to a separate nested repo the parent
  cannot stage (`git add` → "Pathspec is in submodule") — so a task touching
  them would fail at commit time. `/audit` now **preflights** this: when
  `<gitRoot>/.gitmodules` exists it checks every `task.files` entry and STOPS
  with guidance (point `meta.gitRoot` at the submodule, or drop those files)
  instead of failing mid-run.
  - `scripts/audit-status.py` gains `parse_gitmodules()` + `submodule_conflicts()`
    (pure, path-boundary safe: `vendor/child` matches `vendor/child/x` but not
    `vendor/child-other/x`) and a `--submodules <.gitmodules> [--git-root
    <prefix>]` CLI mode (exit 1 on conflict). 22 selftest cases.
  - `/audit:init` no longer routes tasks at files inside a submodule (defers
    them instead); README Troubleshooting documents the boundary.

### Note
Plan-first and secret guards still apply to submodule paths by path (they don't
touch git). Only the per-task commit and the PostToolUse shell-write check are
submodule-boundary limited — both now surfaced rather than silent.

## [0.6.1] - 2026-07-07

Fix: git repo in a subdirectory (found by end-to-end testing against a real Nx
monorepo where the git root was `test/`, not the project dir).

### Fixed
- **The orchestrator assumed the project dir IS the git root.** When the git
  repo lived in a subdirectory, every git operation failed (`not a git
  repository`), the manifest (outside the git tree) could not be committed, and
  `guard-bash-writes` went silent — all four failures were silent. Now:
  - `meta.gitRoot` (+ `gitRoot` in `.claude/audit.config.json`) — path of the
    git root relative to the project dir (default `.`). `/audit` runs
    `git -C <gitRoot>`, runs gates there, and strips the prefix when staging;
    `guard-bash-writes` runs its git check there too.
  - **`/audit` preflight** verifies the git root is a git repo and STOPS with
    guidance if not — turning a silent 4-way break into one clear message. It
    also warns when the manifest lives outside the git root.
  - `/audit:init` detects the git root and sets `meta.gitRoot`; `/audit` reads
    the 0.2.0-era `meta.workspaceRoot` as a fallback, so existing manifests work.
- Validator no longer warns on `phase.description` (now a real schema field) or
  on the 0.2.0-era `meta.notes`/`meta.workspaceRoot`/`meta.baseCommit`/`task.details`
  keys — a 0.2.0-generated manifest dropped from 21 warnings to 0.

### Added
- README: "Git repo in a subdirectory" and "Troubleshooting" sections
  (git-root preflight, stale version-pinned permission after `/plugin update`,
  interpreter/Git-Bash, state files). 185 selftest cases.

## [0.6.0] - 2026-07-07

Agents & full-coverage enforcement: prompt discipline becomes mechanical.

### Added
- **Plugin agents** (`agents/`): the commands now spawn pinned-tool subagents
  instead of free-form ones — `audit-explorer` (Glob/Grep/Read only:
  **mechanically read-only**, used by `/audit:init` fan-out), `audit-executor`
  (no web tools, no nested agents; task execution and review fixes),
  `audit-reviewer` (no edit tools; sign-off review runs the project review
  skill inside the agent, keeping the diff out of the orchestrator's context).
  Tool lists are a hard boundary independent of subagent hook inheritance
  (#43772); commands fall back to general subagents on older Claude Code.
- **`guard-bash-writes.py`** (PostToolUse `Bash` + edit tools): git-status
  diff check that catches ANY shell write into a source file no tool edit and
  no `in_progress` task accounts for — the statically-undecidable residual of
  the PreToolUse text checks (#29709) — and tells the model in-band
  (non-blocking; needs a git repo; `bashWriteCheck.enabled`, default true).
- **State GC**: session state files (incl. forgotten armed bypasses) older
  than 7 days are garbage-collected on prompt submission;
  `detect-plan-skip.py` gains a selftest.
- CI: ten selftest suites (183 cases); GitHub Actions bumped off the
  deprecated Node 20 action majors; repo `.gitignore` covers the dogfood
  manifest's runtime artifacts (`*.lock`, `audit-report.*`).

### Changed
- `_config.py`: shared `source_exts()` (one definition of "source file" for
  the shell-write guards and the TDD nudge) and `bashWriteCheck` defaults.
- CONTRIBUTING: commands-vs-skills decision re-evaluated with agents shipped
  (still NO-GO — invocation surface unchanged); plugin evals documented as
  deferred while `claude plugin eval` is early access (schema not public).
- `remind-tdd.py` docstring: the throttle is per-session, not global
  (concurrent sessions throttle independently).

## [0.5.0] - 2026-07-07

Features for team use (Azure DevOps focus).

### Added
- **`/audit:sync`** (`push [bugs|tasks|all]` · `pull` · `status`): mirrors manifest
  bugs/tasks into Azure DevOps work items and back. Contract = the `az boards`
  CLI (headless-capable; azure-devops MCP tools as an optional fast-path);
  configured by the new `meta.ado` block; idempotent — the write-back
  `item.ado = {id, url, lastSyncedAt}` lands immediately after each create so
  interrupted runs converge; plan + confirmation before the first outward
  write; credentials never stored or printed (`az login` /
  `AZURE_DEVOPS_EXT_PAT`).
- **`scripts/audit-status.py`** — headless rollup + **CI gate**: `--json`
  (phases/tasks/bugs/ready summary), `--gate` exits 1 on tripped conditions
  (default `invalid,open-high-bugs,blocked-tasks`; also `open-bugs`,
  `in-progress` via `--fail-on`). Wired into this repo's CI against the
  dogfood manifest; `docs/examples/azure-pipelines.yml` shows the
  validate → gate → report pipeline for consuming repos.
- **`/audit report`** + **`scripts/render-report.py`** — self-contained
  HTML + Markdown status report (inline CSS, zero network fetches; every
  manifest string escaped, only http(s) URLs rendered as links), publishable
  as a CI artifact.
- **Concurrency lock**: mutating subcommands hold `<manifestPath>.lock` —
  a second session is refused with holder info; a stale lock (>60 min)
  offers a confirmed takeover; `status`/`report` never lock.
- Schema (additive): `meta.ado`, `task.ado`, `bug.ado` (`$defs/adoLink`);
  validator checks their shape and accepts the new keys.

### Fixed
- `require-plan` no longer gates the manifest itself or its lockfile when a
  custom `manifestPath` falls outside the exempt globs (previously the
  orchestrator's own manifest writes could be blocked).

## [0.4.0] - 2026-07-07

Release-quality envelope: docs, CI, policies, canonical hook protocol.

### Added
- **CI** (`.github/workflows/ci.yml`): ubuntu + windows matrix running all six
  `--selftest` suites, the launcher fail-loud check, the structural validator and
  ajv (draft 2020-12) over the starter **and** the dogfood manifest, and
  `claude plugin validate` for the marketplace + plugin.
- **Dogfood manifest** `docs/audit/audit-plan.json`: this repo's own roadmap as an
  audit manifest — P1 = shipped v0.3.0 (real commit SHAs), P2 = v0.4.0, P3 = the
  v0.5.0 plan, including a reciprocal `BUG-1 ↔ task` link. CI validates it with the
  plugin's own validator, so the roadmap doubles as a permanent integration fixture
  and a real-world manifest example.
- **Root `README.md`** (repo landing page), **`SECURITY.md`** (threat model,
  fail-mode table, known bypass classes, reporting), **`CONTRIBUTING.md`**
  (dev setup, test matrix, release rule, commands-vs-skills decision record),
  and this **`CHANGELOG.md`**.
- Plugin metadata: `repository` in `plugin.json`; `category`, `tags` and
  `strict: true` on the marketplace entry.

### Changed
- **Blocking hooks speak the canonical PreToolUse protocol**: `require-plan`,
  `guard-edits` and `guard-secrets-read` now emit
  `hookSpecificOutput.permissionDecision: "deny"` JSON with the reason and exit 0,
  instead of the deprecated exit-2 + stderr channel (which is indistinguishable
  from a hook crash). Decision cores are unchanged; selftests assert the JSON shape.
- **Plugin README overhauled**: Requirements section (Python via
  `python3`/`python`/`py`; Windows = Git Bash), runnable copy-paste snippets
  (the unresolvable `<plugin>` placeholder is gone), a prominent
  **"installing arms global hooks"** section with per-project scoping /
  disable / uninstall instructions, guidance for repos without tests, and a
  one-session-per-clone concurrency note.

### Fixed
- `PLUGIN-BUILD-GUIDE.md`: said "four guard hooks" while wiring five; stale note
  claiming the marketplace was renamed to `claude-plugins` (it is `quality-gates`);
  stale hook/validator descriptions predating 0.3.0.

### Release integrity note
Tags are never moved. The `v0.2.0` tag predates the marketplace rename commit
`433dd35` (tagged tree says marketplace `claude-plugins`; `main` after that commit
says `quality-gates`) and there is no `v0.1.0` tag. Fixed forward: from 0.3.0 on,
every release is one commit that bumps `plugin.json` + updates this changelog and
carries the annotated tag; tags are pushed only after CI is green.

## [0.3.0] - 2026-07-07

Hardening: every confirmed correctness defect from the v0.2.0 deep review fixed.

### Added
- `/audit resume` subcommand; `status` flags resumable phases.
- `hooks/py-launch.sh`: interpreter resolution `python3` → `python` → `py`;
  without any interpreter the blocking guards emit `permissionDecision: "ask"`
  JSON (fail-LOUD) instead of the previous silent fail-open on exit 127.
- `_config.py --selftest`; `_configError` marker for present-but-malformed config,
  surfaced once per session by `detect-plan-skip` (which now also announces when a
  `#no-plan` bypass is armed).
- Guard coverage: `NotebookEdit` everywhere; indirect secret reads
  (`git show`/`cat-file`, `source`/dot-source, `cp`/`mv`/`rsync`/`install`);
  shell writes into source files (`sed -i`, `tee`, `>`/`>>` redirects incl.
  heredoc redirects) unless covered by an `in_progress` task; self-edit
  protection for the installed plugin's files; `plan-bypass-*` forgery block.
- Validator: dependency-cycle detection, reciprocal `bug ↔ task` link checks,
  bidirectional `fileIndex ↔ task.files` reconciliation, tests-not-an-object
  finding, unknown-key warnings with did-you-mean, exit codes 0/1/2.
- `phase.desiredOutcome` wired: shown by `status`, given to task subagents,
  addressed by the sign-off summary; `/audit:init` generates it per phase.

### Changed
- **Transactional plan-bypass**: PreToolUse only observes state; PostToolUse
  (fires only after a successful edit) consumes the single-use bypass and records
  the free-file slot — a denied edit no longer burns them.
- Trivial-edit threshold uses **change magnitude** = max(added lines, chars/200,
  removed lines), closing the single-line-blob and mass-deletion loopholes.
- `run <taskId>` gained status guards (done → confirmed re-open; blocked →
  confirmed reset; in_progress → points to resume); phase entry (dev-branch
  verification, `baseRef`, branch creation, `phase.status = "in_progress"`) is
  unified across the `phase`/`next`/`run` paths.
- Test failure vs **infrastructure failure**: a gate that could not run does not
  consume attempts — it stops with a human action item.
- ff-merge fallback: when the development branch advanced, offer `--no-ff`
  (keeps recorded SHAs valid) or stop; rebase is never offered.
- High-risk confirmation is unconditional (the undefined "auto mode" gate is gone).
- Every hook entry has an explicit 10 s timeout (default was 600 s).
- Schema: canonical `$id`, `^BUG-\d+$` pattern on `bug.id`; never-read meta fields
  removed (`signOffChecklist`, `autoMode`, `modelPolicy`, `testPolicy`,
  `reviewPolicy`, `skillsPolicy`, `statusLegend`, `phase.signOff`) — legacy
  manifests still validate.

### Fixed
- **Resume worked on paper only**: it searched for `phase.status == "in_progress"`,
  which nothing ever wrote. The status is now written at phase entry (with a
  pre-0.3 fallback in resume).
- **YAML frontmatter in `commands/*.md` was silently dropped at runtime**
  (`audit.md`'s description contained `: `, so ALL its metadata — including
  `allowed-tools` — never applied; `init.md`'s argument-hint parsed as a YAML
  array). All frontmatter values are now quoted; `claude plugin validate` passes.
- Malformed `.claude/audit.config.json` no longer silently reverts custom secret
  patterns/rules/thresholds to defaults without a signal.
- `/audit` preflight: malformed config stops with the parse error; a missing
  manifest points to `/audit:init`; an unknown subcommand prints usage.
- `AskUserQuestion` added to `/audit`'s `allowed-tools` (it has ~6 human gates).

## [0.2.0] - 2026-07-06 _(tag `v0.2.0`)_

### Added
- `/audit:init` — multi-agent manifest generation (interview → recon → parallel
  read-only explorers → synthesized schema-valid phases/tasks).
- `/audit:task add` — interactive task creation (id allocation, full template,
  fileIndex maintenance, revalidation).
- `/audit:bug` — bug tracking in the manifest's top-level `bugs[]`;
  `fix` materializes a bug into a red-first TDD task (`expectRedFirst`);
  the orchestrator flips the bug to `fixed` + `fixedIn` on the task commit.
- `remind-tdd.py` — non-blocking PostToolUse TDD nudge (throttled,
  manifest-aware, configurable).
- Schema: top-level `bugs[]`, `task.bugId`; shared `reference/manifest-conventions.md`.

### Known issue (documented 0.4.0)
The `v0.2.0` tag was cut before the marketplace rename to `quality-gates`
(`433dd35`) with no version bump — the tagged tree and `main` disagree on the
marketplace name while both claim 0.2.0.

## [0.1.0] - 2026-07-06 _(untagged)_

### Added
- Initial public extraction of the internal audit tooling, IP-scrubbed and
  de-coupled: `/audit` orchestrator (manifest-driven phases/tasks, branch-per-phase,
  per-task model + skills subagents, TDD/regression/gate-only discipline, phase
  sign-off), guard hooks (`require-plan`, `detect-plan-skip`,
  `guard-secrets-read`, `guard-edits`), `_config.py` per-repo config layer,
  JSON Schema + dependency-free structural validator, starter templates,
  MIT license, marketplace `quality-gates`.
