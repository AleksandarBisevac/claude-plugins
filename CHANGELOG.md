# Changelog

All notable changes to the `quality-gates` marketplace and its `audit` plugin.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the
`audit` plugin's `plugin.json` version, tagged `v<version>` on this repo.

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
