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
        layout.md                         # /audit:layout — pick the manifest layout, either direction
        migrate.md                        # /audit:migrate — legacy spelling of `/audit:layout sharded`
        init.md                           # /audit:init — multi-agent manifest generation
        task.md                           # /audit:task — add/scope/move/cancel a task, answers as flags
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
        guard-history-rewrite.py          # refuse a git command that would orphan a recorded task.commit
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
        manifest/                         # the manifest domain: the layout, the registry, the validator, the writers
          _manifest_io.py                 # dual-format loader/writer (single-file OR index+shards)
          _ado_conventions.py             # meta.ado.conventions: what an item must look like to belong
          _ado_fields.py                  # meta.ado.fields: what this project supplies to those fields
          _ado_parent.py                  # where ONE item hangs on the board, and whether that place can be true
          resolve-ado-parent.py           # the door onto it: resolve, check the hierarchy, refuse a link nothing can build, build the cached ladder
          _ado_tracked.py                 # whether an item belongs on the shared board at all, and why it does not
          resolve-ado-tracked.py          # the door onto it: answer for a manifest or a scope, and never refuse a declared intention
          check-ado-item.py               # the gate /audit:sync push runs an item through before creating it
          _ado_connect.py                 # every decision /audit:sync connect makes: transport, auth path, probe, process
          ado-connect.py                  # the door onto it: the read-only ladder to a first working connector
          _ado_drift.py                   # who wrote a linked work item last, and whether pushing overwrites them
          explain-ado-drift.py            # the door onto it: the status table's third reading, and push's plan line
          _ado_fetch.py                   # the linked side of a board in ONE query per chunk, bounded, with the field list that is a contract
          fetch-ado-items.py              # the door onto it: every linked item in one call per chunk, partial answers named rather than hidden
          read-ado-links.py               # the MANIFEST side of that: which items are linked, and what ADO state each one's status means
          resolve-branch.py               # the door onto _branch: this phase's parent branch and branch name
          repair-commits.py               # put the manifest back to the truth after a history rewrite
          _proposals.py                   # the proposal lifecycle: refusals, closure, collision remap, lock+apply+validate, and the rows both surfaces list
          materialize-proposal.py         # the command door onto it: arguments, the list table, printing, exit codes
          _areas.py                       # meta.areas registry + reviewSkill/skills resolution
          _branch.py                      # where a phase's branch forks from, and what it is called
          _priority.py                    # which READY task runs first: the one expression of execution order
          set-priority.py                 # the door onto it: pin a phase, or unpin it, under the index lock
          _commit_trail.py                # is a recorded task.commit still reachable from any ref?
          _manifest_rules.py              # the ORDER those rules run in, and the surface consumers import
          _manifest_vocab.py              # the manifest's words + the shape checks every level shares
          _manifest_phases.py             # the one walk over phases/tasks, and what a phase carries
          _manifest_ado.py                # meta.ado: the connector config, one front door with the panel
          _manifest_typos.py              # did-you-mean: a model id / skill name one slip from another
          _manifest_crossrefs.py          # ids, refs, cycles, fileIndex, bug links, parked proposals
          _warning_groups.py              # the SHAPE those warnings print in: many that differ only in the item they name, as one line
          validate-manifest.py            # the command over those rules: read a file, print, exit 0/1/2
          audit-task.py                   # /audit:task add + /audit:phase add + cancel doer: id allocation, full template init, lock+journal
          migrate-manifest.py             # /audit:layout doer: --to=sharded|single-file (backup+restore)
        governance/                       # the governance domain: the policy, the lock, the audit trail
          _policy.py                      # capability policy: shape, validation, required -> deny -> allow -> default
          _locks.py                       # the lock library: where one lives, is it live, acquire/release
          audit-lock.py                   # the CLI over it: acquire/release/status as exit codes
          _journal_io.py                  # the audit trail: row shape, hash chain, read/append/verify
          _evidence_io.py                 # the test-evidence record: where it lives, and what a row may say
          audit-journal.py                # the CLI over it: append/verify/show/archive
          _invariants.py                  # the orchestrator's rules, re-derived from git + shard + journal + ledger
          verify-invariants.py            # the CLI over it: one phase or --all, breach = exit 1
          commit-audit-state.py           # commits the phase's manifest file + journal + evidence and NOTHING else, or says there is none
          run-test-gate.py                # runs a phase's gate bracketed by a tree snapshot; counts what ran; states what it touched
        _output.py                        # stdout/stderr that degrade a glyph instead of crashing
        _fmt.py                           # the one token/cost formatter, shared by usage + report + status
        _cli_fmt.py                       # the one place CLI color lives: --color resolution + paint roles
        _loader.py                        # the one way scripts/ loads a sibling script as a library, one cache policy
        _ui_theme.py                      # shared visual tokens (colour/spacing/type/labels) for report + panel
        _deps.py                          # the module layer table, checked against the real import graph every run
        _refs.py                          # what one file claims about another: script paths stat'd, and the document link graph
        usage/                            # the usage domain: the ledger, the arithmetic over it, the CLI
          _usage_core.py                  # usage arithmetic: the price table, the hour bucket, the roll-ups, the row readers
          _usage_spend.py                 # spend through time: series, window compare, cache profile
          _usage_economics.py             # what the work cost: unit economics, cost bands, budgets, retried vs blocked
          _usage_routing.py               # cost per task per model WITHIN a risk band, and the advice that survives its gates
          _usage_coverage.py              # the ledger seen whole: attribution coverage, the 12-month roll-up
          _usage_bench.py                 # the timer over those four passes, and the fixture it times them on
          usage_ledger.py                 # token-usage metering core: transcript scan, dedup, attribution
          audit-usage.py                  # /audit:usage: token spend, attributed
        config/                           # the config domain: the config file's validator and the self-description over both schemas
          _config_rules.py                # every rule .claude/audit.config.json is held to + its enums
          validate-config.py              # the command over those rules: read a file, print, exit 0/1/2
          _help.py                        # zero-token self-description: schema field help + how-it-works topics
        status/                           # the status domain: the headless rollup and the setup diagnostics over it
          _status_facts.py                # what the manifest SAYS: rollup, readiness, submodules, the gate
          audit-status.py                 # the command over those facts: human render + --json/--gate
          audit-doctor.py                 # /audit:doctor: the ORDER of the checks, the render and the CLI
          _doctor_report.py               # what the six check modules share: the Report collector + _load
          _doctor_setup.py                # interpreter, sandbox + secret rules, git root, config, manifest, shards, submodules
          _doctor_policy.py               # meta.areas, the capability policy, the buildCommands runners
          _doctor_ado.py                  # the ADO connector's operational half (transport, switches, links)
          _doctor_trail.py                # has anything run here: hook state, usage ledger, journal chain
          _doctor_completions.py          # the task.complete receipts against the plan, git and the ledger
          _doctor_hygiene.py              # what is HELD (locks) and what is LEAKING (local artifacts in git)
          _gate_feed.py                   # the plan-gate events feed's prune rule: which rows no longer belong
          audit-logs.py                   # /audit:logs: the door onto that rule - parse, render, exit code
        report/                           # the report domain: the FIRST subdirectory under scripts/
          render-report.py                # self-contained HTML+MD report (CI artifact)
          _report_ui.py                   # reads the ordered parts under scripts/ui/report{,-css}/, assembles _CSS/_SCRIPT
          _report_html.py                 # HTML fragment builders for the report: escaping, chips, table cells
          _report_usage.py                # the Usage section's ORDER: assembly + the shared data payload
          _usage_viz.py                   # how the section formats a number and draws a bar
          _usage_load.py                  # the ledger read - the Usage section's only I/O
          _usage_overview.py              # what shows on first paint: strip, trend, ranked lists, budget
          _usage_detail.py                # everything folded behind the `Detail` disclosure
          _usage_markdown.py              # the Usage section's Markdown twin
          _report_page.py                 # the report as a whole document: vocab, table, render_html
          _report_md.py                   # the report's Markdown twin (render_md), embedded in the page
          _evidence_view.py               # the evidence-ledger read - the test-gate column's only I/O
        panel/                            # the panel domain: the server, the page it assembles, the read and write sides
          panel-server.py                 # localhost control-panel web UI (config + composition)
          _panel_ui.py                    # reads panel.html + the ordered parts under scripts/ui/panel{,-css}/, assembles UI_HTML
          _panel_page.py                  # the assembled page: the substitution chain -> UI_HTML + UI_TEMPLATE
          _panel_discovery.py             # discovers skills/agents/MCP servers this project can reach
          _panel_settings.py              # the Settings form's schema + the write-path key allow-lists
          _panel_paths.py                 # where a project's files are + the three modules the panel reads through
          _panel_viewer.py                # who is driving the panel, and the identity cache behind it
          _panel_composition.py           # the plan as shown: phase/task rows, bugs, the ADO banner, areas
          _panel_policy.py                # the capability policy, and what it resolves to for what is installed
          _panel_runstate.py              # locks + liveness, the on-disk change stamp, the Plan gate card
          _panel_usage.py                 # the Usage tab's facts, and the one manifest read per request
          _panel_state.py                 # the panel's READ side: everything GET /api/* answers with
          _panel_write.py                 # the panel's WRITE side: everything PUT /api/* actually does
        demo/                             # the demo domain: the two synthetic fixtures the screenshots and CI are built from
          _demo_cast.py                   # the identities both fixtures attribute to, so the owner join matches
          gen-demo-manifest.py            # synthetic LARGE manifest fixture for demos/screenshots/CI
          gen-demo-usage.py               # synthetic usage ledger fixture, consistent with a real manifest
        ui/                               # four directories of ordered parts (report/, report-css/, panel/, panel-css/) + panel.html, no .py
      tests/                              # selftest blocks moved OUT of the modules they test (all of them)
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
  _ado_connect -> _output
  _ado_conventions -> _output
  _ado_fields -> _output
  _ado_parent -> _output
  _ado_tracked -> _output
  _areas -> _output
  _branch -> _output
  _cli_fmt -> _output
  _commit_trail -> _output
  _demo_cast -> _output
  _deps -> _output
  _fmt -> _output
  _journal_io -> _output
  _loader -> _output
  _locks -> _output
  _manifest_io -> _output
  _manifest_vocab -> _output
  _policy -> _output
  _priority -> _output
  _refs -> _output
  _ui_theme -> _output
  _usage_core -> _output

L2:
  _ado_drift -> _manifest_io, _manifest_vocab, _output, _usage_core
  _config_rules -> _loader, _output, _policy
  _doctor_report -> _loader, _output
  _evidence_io -> _journal_io, _locks, _manifest_io, _output
  _gate_feed -> _journal_io, _loader, _output, _usage_core
  _help -> _areas, _journal_io, _loader, _manifest_vocab, _output, _policy, _ui_theme
  _manifest_ado -> _ado_conventions, _ado_fields, _manifest_vocab, _output
  _manifest_crossrefs -> _ado_parent, _manifest_io, _manifest_vocab, _output, _priority
  _manifest_phases -> _ado_parent, _ado_tracked, _areas, _manifest_io, _manifest_vocab, _output
  _manifest_typos -> _areas, _manifest_vocab, _output
  _panel_ui -> _output, _ui_theme
  _report_html -> _areas, _manifest_io, _output, _priority, _ui_theme
  _report_ui -> _output, _ui_theme
  _status_facts -> _areas, _manifest_io, _output, _priority, _usage_core
  _usage_coverage -> _output, _usage_core
  _usage_economics -> _output, _usage_core
  _usage_routing -> _manifest_io, _output, _usage_core
  _usage_spend -> _output, _usage_core
  _warning_groups -> _fmt, _manifest_io, _output

L3:
  _ado_fetch -> _ado_drift, _output
  _doctor_ado -> _ado_drift, _ado_tracked, _doctor_report, _output
  _doctor_hygiene -> _locks, _output
  _evidence_view -> _evidence_io, _output, _report_html, _status_facts
  _manifest_rules -> _branch, _manifest_ado, _manifest_crossrefs, _manifest_io, _manifest_phases, _manifest_typos, _manifest_vocab, _output
  _panel_discovery -> _help, _manifest_io, _output
  _panel_paths -> _config_rules, _loader, _manifest_io, _output, _status_facts
  _panel_settings -> _config_rules, _output
  _usage_bench -> _output, _usage_core, _usage_coverage, _usage_economics, _usage_routing, _usage_spend
  _usage_viz -> _fmt, _output, _report_html
  usage_ledger -> _manifest_io, _output, _usage_core, _usage_coverage, _usage_economics, _usage_routing, _usage_spend

L4:
  _doctor_completions -> _commit_trail, _doctor_report, _evidence_io, _journal_io, _output
  _doctor_policy -> _branch, _doctor_report, _output
  _doctor_setup -> _config_rules, _doctor_report, _manifest_rules, _manifest_vocab, _output, _status_facts, _warning_groups
  _doctor_trail -> _doctor_report, _journal_io, _output
  _invariants -> _branch, _commit_trail, _evidence_io, _journal_io, _manifest_io, _manifest_rules, _output, _status_facts, usage_ledger
  _panel_composition -> _ado_drift, _ado_parent, _ado_tracked, _areas, _branch, _evidence_io, _manifest_io, _output, _panel_paths, _priority, _status_facts
  _panel_page -> _loader, _output, _panel_settings, _panel_ui, _ui_theme
  _panel_policy -> _areas, _manifest_io, _output, _panel_discovery, _panel_paths, _policy
  _panel_runstate -> _evidence_io, _journal_io, _locks, _output, _panel_paths
  _panel_usage -> _areas, _manifest_io, _output, _panel_paths
  _panel_viewer -> _loader, _output, _panel_discovery, _panel_paths
  _proposals -> _fmt, _locks, _manifest_io, _manifest_rules, _manifest_vocab, _output
  _usage_detail -> _output, _ui_theme, _usage_viz
  _usage_load -> _loader, _output, _report_html
  _usage_markdown -> _output, _ui_theme, _usage_viz
  _usage_overview -> _fmt, _output, _ui_theme, _usage_viz

L5:
  _panel_state -> _evidence_io, _help, _journal_io, _manifest_io, _manifest_rules, _output, _panel_composition, _panel_discovery, _panel_paths, _panel_policy, _panel_runstate, _panel_usage, _panel_viewer, _proposals, _report_html
  _report_md -> _output, _report_html, _usage_markdown
  _report_usage -> _output, _usage_detail, _usage_load, _usage_markdown, _usage_overview, _usage_viz

L6:
  _panel_write -> _ado_parent, _ado_tracked, _areas, _gate_feed, _journal_io, _locks, _manifest_io, _output, _panel_settings, _panel_state, _policy, _priority, _proposals, _ui_theme, _warning_groups
  _report_page -> _fmt, _manifest_io, _output, _report_html, _report_md, _report_ui, _report_usage, _status_facts

L7:
  ado-connect -> _ado_connect, _output
  audit-doctor -> _cli_fmt, _doctor_ado, _doctor_completions, _doctor_hygiene, _doctor_policy, _doctor_report, _doctor_setup, _doctor_trail, _output
  audit-journal -> _journal_io, _output
  audit-lock -> _locks, _output
  audit-logs -> _gate_feed, _output
  audit-status -> _areas, _cli_fmt, _evidence_io, _fmt, _invariants, _loader, _manifest_io, _manifest_rules, _output, _panel_discovery, _proposals, _status_facts, _ui_theme
  audit-task -> _areas, _manifest_io, _output, _panel_write, _proposals, _warning_groups
  audit-usage -> _areas, _cli_fmt, _fmt, _loader, _locks, _output, _ui_theme
  check-ado-item -> _ado_conventions, _ado_fields, _ado_parent, _output
  commit-audit-state -> _evidence_io, _invariants, _journal_io, _manifest_io, _output
  explain-ado-drift -> _ado_drift, _manifest_io, _output
  fetch-ado-items -> _ado_fetch, _manifest_io, _output
  gen-demo-manifest -> _demo_cast, _evidence_io, _journal_io, _loader, _manifest_io, _output
  gen-demo-usage -> _demo_cast, _loader, _output
  materialize-proposal -> _manifest_io, _output, _proposals, _warning_groups
  migrate-manifest -> _manifest_io, _manifest_rules, _output
  panel-server -> _manifest_io, _output, _panel_discovery, _panel_page, _panel_settings, _panel_state, _panel_write, _ui_theme
  read-ado-links -> _ado_drift, _ado_tracked, _manifest_io, _output
  render-report -> _evidence_io, _evidence_view, _fmt, _loader, _manifest_io, _manifest_rules, _output, _report_html, _report_md, _report_page, _report_ui, _report_usage, _status_facts, _ui_theme
  repair-commits -> _commit_trail, _journal_io, _locks, _manifest_io, _manifest_rules, _output
  resolve-ado-parent -> _ado_parent, _manifest_io, _output
  resolve-ado-tracked -> _ado_tracked, _manifest_io, _output
  resolve-branch -> _branch, _manifest_io, _output
  run-test-gate -> _evidence_io, _journal_io, _manifest_io, _output
  set-priority -> _manifest_io, _output, _panel_write, _priority, _warning_groups
  validate-config -> _config_rules, _output
  validate-manifest -> _manifest_io, _manifest_rules, _output, _warning_groups
  verify-invariants -> _invariants, _manifest_io, _output
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
- PreToolUse `Bash` → `guard-history-rewrite.py` (fail mode **ask**)
- PreToolUse `Edit|Write|MultiEdit|NotebookEdit` → `guard-edits.py`, then `require-plan.py` (both **ask**)
- PreToolUse `Skill|Task|Agent|mcp__.*` → `guard-capabilities.py` (fail mode **ask**)
- PostToolUse `Edit|Write|MultiEdit|NotebookEdit` → `require-plan.py` (state commit), `remind-tdd.py`, `guard-bash-writes.py` (records tool edits), `journal-writes.py` (records manifest/config writes; all **open**)
- PostToolUse `Bash` → `guard-bash-writes.py` (the diff check), `journal-writes.py` (the `dangerouslyDisableSandbox` row **and** the digest sweep that catches a manifest written by a shell command; both **open**)
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
(`rel_path`, `within_root`, `matches_exempt`, `strip_line_suffix`, `in_progress_files`,
`in_progress_task_map` — the latter exposes each covering task's `tests.mode` for remind-tdd).
`within_root` is the containment question `rel_path` cannot answer: relpath hands a path
in another tree back as a run of `..` segments, an ordinary string that read as repo
source and got a scratch file in the system temp directory refused by the plan gate. It
lives here rather than in the one hook that reported it because three hooks ask it and
`SECURITY.md` promises two of them agree; it never calls `relpath`, which RAISES across
Windows drives.
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
`bashWriteCheck.enabled` (default true). `--selftest` (incl. a real `git init`
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
free is the failure mode this whole feature exists to avoid. `scripts/config/_help.py` reads its
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

**P0-S: the environment reached INDIRECTLY, and where this hook's reach ends.** `printenv` was
anchored to the start of a clause, so any wrapper in front of it walked straight past —
`direnv exec . printenv X` printed a secret with no deny, no gate message and no journal row.
The verb is now a dump wherever it stands (a rule about what may not PRECEDE it, because an
inventory of legal wrappers cannot be written and would be short by one), `direnv dump`/`export`
join it, and `.envrc` — the file the live report was actually about — joins the secret sets.
`process.env` moved from the secret-FILE rule to the environment rule: the whole object and a
token-shaped name are refused, one ordinary named variable is not, and being refused as "reading
a secret file's contents" was the same false-positive class as F-P-7 one layer up. Finally the
hook reads `dangerouslyDisableSandbox` off `tool_input` and refuses the COMBINATION of the
sandbox being off with a command that reaches the environment layer — bounded to the
combination, because an unsandboxed run is legitimate and denying all of them gets the plugin
switched off. **The class is not closed and cannot be**: these matchers read tool-call text and
never observe I/O, so the ceiling is friction plus evidence — `journal-writes` records every
other unsandboxed run, and SECURITY.md states the boundary in full.

### `plugins/audit/hooks/guard-history-rewrite.py`
Refuses a git command that would orphan a commit the manifest records. `task.commit` holds each
task's SHA and `bug.fixedIn` is derived from it, which is why `reference/orchestrator.md` names
force-push and rebase as invariants. Those bind the ORCHESTRATOR; a human at the same terminal is
not the orchestrator, and the damage is the same — `/audit:doctor` then reports "the manifest
names a commit git does not have" and the trail is a list of ghosts.

**It binds to the effect, not the command name, and that is the whole design.** `git reset
--hard` is not one operation: with no ref it discards uncommitted work and moves no branch
pointer, which is exactly what abandoning a botched task attempt looks like and is **allowed**;
with a ref it is decided by asking git — `merge-base --is-ancestor` for each recorded SHA — and
refused only when one of them would stop being reachable. Force-push, `--orphan` and
`filter-branch` have no ancestry question to ask and are refused outright while any SHA is
recorded.

A guard that refused every `reset --hard` would fire on correct work, and a guard that fires on
correct work gets switched off, after which it protects nothing. That failure mode is already in
this project's history (F-P-24, and the read-vs-write class `guard-secrets-read` was fixed for
before it), so the ancestry check is not an optimisation — it is the reason the guard is allowed
to exist. `tests/test_guard_history_rewrite.py` is written the same way round: its ALLOW cases
are the load-bearing ones, and each is proven red by a mutation chosen to tell the two versions
apart rather than merely to break something.

Undecidable resolves to allow: an unreadable manifest, an unresolvable ref, or a git that will
not answer all pass. A manifest with no recorded SHAs makes the guard inert — nothing to orphan
is nothing to refuse, and a guard that warned anyway would be teaching people to ignore it.

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
PostToolUse (Edit|Write|MultiEdit|NotebookEdit **and Bash**) recorder: every write to the
manifest (index or phase shard) or to `.claude/audit.config.json` appends one row to the
audit trail via `scripts/governance/audit-journal.py`. NO stdout at all — a recorder that talks turns
every manifest edit into transcript — and every failure is silent, because a journal that
cannot be written must not break the write it was recording. A hook rather than an
instruction on purpose: a model that forgets to log a change leaves a gap that looks exactly
like a covered-up one. Config `journal.enabled`. `--selftest` (incl. an end-to-end
append + verify).

**The two passes, and why the tool is not part of the question (F194).** Edit fragments are
not parseable JSON, so a field-level diff can only come from remembering the file as it
stood before the write. The PreToolUse pass snapshots each recorded path into a
per-(session, target) slot under `stateDir`; the PostToolUse pass reads that slot, diffs old
against new by id over the state fields, emits the derived `task.complete` / `task.commit` /
`phase.signoff` rows, and then **refreshes the slot** to the state it just recorded. The
refresh is the whole repair: the derivation used to hang off a slot only an edit-tool Pre
pass ever wrote, so a session that wrote the manifest through `python3 -c` in a Bash call
left a chain that verified perfectly over a history with none of those rows in it — the
worst combination available, and the same dependency a hook was chosen over a prompt to
avoid, one layer down. Refreshed, the baseline is the manifest as of the last row in the
journal, so the Bash pass can ask the FILE instead of the payload: for each recorded path —
the index, the shards beside it, the config — is the digest still the one the slot
remembers? The Pre pass **stays**, because the slot is keyed per session and without it the
first write of every session would have no baseline. Two limits are stated in the row rather
than left to be discovered: a path with no slot at all is seeded and claimed nothing about,
and a path that moved with no parseable pre-image carries `DERIVATION_MISSED` in its summary
and in `details.reason`.

Also PostToolUse on **Bash**, for one event that is not about the plan: a call carrying
`dangerouslyDisableSandbox` appends `bash.unsandboxed` with a DIGEST of the command, its
byte length, its program name and the cwd relative to the repo (`commandSha256`,
`commandBytes`, `program` and `cwd` are `_journal_io.DETAILS_KEYS` entries; `command` is
deliberately NOT one, which is what closes that channel by construction — the journal is
committed on purpose, so command text in a row is CWE-532 in a file that ships). The
flag — not the tool name — is what is read, and it is read **before** the repo root or the
config, so an ordinary Bash call leaves this hook having touched nothing and the journal
cannot decay into a shell log. It prevents nothing: PostToolUse is after the fact, and the
escape hatch is legitimate. What was wrong is that the event was invisible everywhere, which
is the half of P0-S `guard-secrets-read` cannot do — see SECURITY.md's *friction and
evidence* section for the ceiling this pair reaches together.

### `plugins/audit/hooks/guard-capabilities.py` (v0.30.0)
PreToolUse (`Skill|Task|Agent|mcp__.*`) enforcer for the `policy` config block: which skills,
subagents and MCP tools may be used in this repo, optionally scoped to the monorepo areas with
work in progress. The rule itself is NOT here — `scripts/governance/_policy.py` owns the resolution, the
panel previews it and the doctor checks it through the same function — so this file is the
enforcement half only. Inert by default and short-circuits before reading a manifest; every
refusal names the rule that produced it. `onViolation` picks deny / ask / warn, and warn is a
`systemMessage` rather than a `permissionDecision`, which would bypass the permission system.
Leaves a throttled marker in `stateDir` so `/audit:doctor` can say whether the matchers ever
reach it (subagent hook inheritance is not guaranteed). `--selftest`.

### `plugins/audit/hooks/meter-usage.py`
Stop / SubagentStop / SessionEnd hook that turns transcript JSONL into usage-ledger rows.
Claude Code hands hooks a `transcript_path` but no token counts, so this tails that file
(plus the session's subagent transcripts) from a saved byte offset, attributes each message
to a phase/task, and appends aggregated rows — never blocking, and driven by file offsets so
it stays correct regardless of which of the three events fired. Config lives under
`.claude/audit.config.json` -> `usage` (enabled/ledgerDir/authorMode/backfillOnFirstRun/
maxScanBytes/pricing); the mechanics (dedup, attribution precedence) live in `usage_ledger.py`.

### `plugins/audit/scripts/manifest/_branch.py`
Where a phase's branch comes from and what it is called — the two questions that used to have
one hard-coded answer each. `parent_branch()` resolves `phase.parentBranch ?? meta
.developmentBranch`, the same chain `_areas` uses for the review skill, so a phase can integrate
into a story branch, a release line, or another phase's branch instead of always into the
repository's development branch. `compose()` expands `meta.branch.template` — `{type}`,
`{initials}`, `{phase}`, `{slug}` — into the name.

**It is Python because a template cannot be followed from prose.** `reference/orchestrator.md`
could say "compose `<prefix>/<phaseId>-<slug>`" while the shape was fixed, and a reader would get
it right every time. A template has cases: an absent `{initials}` must collapse together with the
separator behind it, or the result is `feature//p2-…`, which git rejects. `expand()` is that rule
with the separator walk written once, and `ref_violations()` is the subset of `git
check-ref-format` a template can actually violate, reported as a list because a bad template
usually breaks more than one rule at a time.

`meta.branchPrefix` is not deprecated by any of this. `config()` reproduces the pre-0.44 shape
*as a template*, so there is one expansion path rather than two that must be kept agreeing, and
it returns a `basis` naming which key decided the convention — the two produce different names
from the same manifest, and a reader looking at a branch could not otherwise tell which was in
force. Every other answer here carries its basis for the same reason: `parent_branch()` reports
`is_development`, because a phase that merged into a story branch has **not** reached the
development branch, and a sign-off report that stays quiet about that reads as "landed".

`approved_globs()` derives the `<type>/*` patterns `reference/orchestrator.md` pre-approves for
`git switch` / `merge --ff-only` / `branch -d`. Derived rather than listed, because a stale list
fails as a permission prompt on every branch operation — loud enough to notice, confusing enough
to be blamed on the harness instead of on the config.

### `plugins/audit/scripts/manifest/resolve-branch.py`
The door onto `_branch`. `resolve-branch.py <manifest> --phase P2` prints the parent branch, the
branch name and the type, each with the key that decided it; `--globs` prints the pre-approved
branch patterns; `--json` gives the same answers as an object.

It is a command and not a paragraph in `reference/orchestrator.md` for the reason the module
exists — a template has cases prose cannot carry — and a command rather than a `python3 -c`
one-liner for the reason `check-ado-item.py` gives: a one-liner naming a source path is the shape
`guard-secrets-read` refuses, so it would be blocked on the machines that most need it.

**Advisory, not a gate**, per `SECURITY.md`'s split — with one exception. A composed name git
would reject exits 1, because the very next command (`git switch -c`) fails anyway and failing
here is the version that says why. Everything else reports and returns 0: a type outside
`meta.branch.types` warns that branch operations on it will prompt, and a phase whose parent is
not the development branch prints the note the sign-off report must repeat — that the work has
**not** reached the development branch until that parent is itself merged.

### `plugins/audit/scripts/manifest/_priority.py`
Which READY task the orchestrator reaches for first. Execution order used to be implicit in the
array — `phases[]` in written order, then task id inside a phase — so the only way to say "this
phase first" was to physically move the phase, which is a structural edit of the whole file and,
in the sharded layout, an edit of the index. Nobody does that in flight, and the workaround was to
hang `blockedBy` off every *other* phase.

**One sentence closes the whole class of bugs a scheduler would open:** *priority re-sorts only
tasks that are already ready; it never makes an unready task ready and never skips a dependency.*
`_status_facts.ready_tasks()` decides readiness exactly as before and this only sorts its output,
so a pin cannot break correctness — only order. A phase pinned first whose own `blockedBy` is
unsatisfied is therefore **skipped**, and `pinned_but_blocked()` exists so the skip is *said*:
`rollup()` carries the sentence as `priorityNote`, and the CLI, both reports and the panel each
print that one key rather than four renderings that drift.

**An absent priority means unprioritised** — not tier 0, not a middle tier. It sorts after every
pinned phase and keeps manifest order among its peers, which is a testable property rather than a
taste: adding a pin to one phase must not re-sort the rest, and a plan with no `priority` anywhere
must order exactly as it did before the field existed. That last one is the case that goes red if
`sort_key` ever becomes unconditional.

Layer 1, for `_branch`'s reason and in the same words: four surfaces need the same answer —
`_status_facts` for the ready list, `_manifest_crossrefs` for the warnings, `_panel_composition`
for the control and `set-priority.py` for the write — and a second expression of the order would
*be* a second order. It reaches nothing but `_output`. Two things it deliberately does not own:
`TERMINAL` and the unmet-refs map are `_manifest_io`'s, at the same layer and so not importable,
and they arrive as arguments — readiness must never have a second opinion. `maxTier` is a *config*
value, so `over_max()` takes it rather than carrying a default that would be a second copy of
`hooks/_config.py`'s.

Tier 1 is the only unique tier, and uniqueness is held three ways rather than one: the write path
refuses a second holder and **names the current one**, the validator reports a doubled tier as a
**warning** (never a finding — see below), and `tier_one_holder()` gives a deterministic tie-break,
first in manifest order. `priority` is **index-only** in the sharded layout
(`_manifest_io.INDEX_ONLY_FIELDS`); a copy found in a shard body is ignored *and reported*, by
`_manifest_io.index_only_in_bodies()`, because the assembled manifest has already dropped it and
that is precisely the state a reader must be told about.

**Every priority rule is a warning, and that is the decision.** A finding would make the manifest
invalid — refusing the next `/audit:task add`, redding `--gate` on the `invalid` condition, and
making `set-priority.py --force` roll back the write it was explicitly asked to force. A
disagreement about *order* must not stop the pipeline; it must not be silent either.

### `plugins/audit/scripts/manifest/set-priority.py`
The door onto `_priority`, and the writer behind `/audit:phase priority` (and behind
`/audit:task priority`, its legacy spelling — one writer, two names).
`set-priority.py <manifest> <phaseId> <tier>` pins a phase, `--clear` unpins it, `--force` writes a
second holder of tier 1 anyway. It writes **one file, the index** — in the sharded layout the stub,
in the single-file layout the manifest itself — under the index lock, revalidates from disk, rolls
every written byte back on findings, and appends a `phase.priority` journal row carrying both ends
of the change.

Whether tier 1 is free is asked of `_priority.tier_one_holder()`, **the same function the panel's
write path asks**. That is the Policy tab's arrangement applied to a second feature: the verdict a
UI shows comes from the function the writer calls, so the panel cannot promise a write the CLI
refuses. `priority.maxTier` is printed as a note and nothing is clamped to it — a clamped value is
a file that says one thing and a run that does another.

Its lock, project resolution, snapshot and rollback are `_panel_write`'s functions rather than
copies: two writers with two rollbacks are two answers, and reaching `audit-task.py` through the
loader would have been an entry point loading an entry point — the edge `KNOWN_LAYER_DEBT` exists
to keep at zero new entries.

### `plugins/audit/scripts/manifest/_commit_trail.py` + `repair-commits.py`
Is every recorded `task.commit` still reachable, and what to write when one is not. The manifest
names a SHA per finished task and derives `bug.fixedIn` from it; that is the audit trail, and it
is a trail only while git still reaches every commit it names.

**Existence is not reachability, and the gap between them was a real hole.** `/audit:doctor`
asked `git rev-parse --verify` alone — which answers *is this object in the store* — so a
`git reset --hard` that orphaned three task commits left all three reporting green until a
`gc` ran, at which point they turned from recoverable into gone with no event in between for
anyone to notice. `dangling()` therefore returns **three** classes: `missing` (git has no such
object — fabricated, or collected), `unreachable` (the object is there and no ref reaches it —
a rewrite, still recoverable), and `unchecked` (git could not be asked, which is an unasked
question and not a clean trail). The reachability test costs one call per commit, so an ancestor
check against HEAD runs first and settles the overwhelming majority.

`repair-commits.py` is the door, and what it refuses to do is the point. It does **not**
re-anchor: no search for a commit with the same message or the same tree, because the commit the
task was verified against is gone and a plausible substitute makes the trail read as intact when
it is not. It nulls the unreachable SHA and writes a journal row carrying what was there, so the
manifest says *this commit is no longer reachable* — which is true. Report mode is the default
and writes nothing; `--apply` takes the index lock, revalidates before saving, and refuses rather
than leave a half-repaired manifest. Where a commit is merely unreachable, the report says so and
points at **restoring a branch onto it** first — clearing is the fallback, not the first move.

### `plugins/audit/scripts/manifest/_areas.py`
The `meta.areas` registry and everything that resolves against it. A phase's `area` tag (free
text, since v0.16) is only a grouping label; this module is where a tag becomes a thing with
properties — a `root`, a `description`, a `reviewSkill`, `skills` — and it implements, once, the
two precedence rules every surface quotes identically: `phase.reviewSkill ?? areas[tag]
.reviewSkill ?? meta.reviewSkill` for the review skill, and area-skills-then-task-skills
(deduped, area first) for the executor. Registration stays optional in both directions;
`review_skill_conflicts()` finds the case where a multi-tag phase's areas disagree, so a
tie-break decided by write order stays visible instead of silent.

### `plugins/audit/scripts/governance/_policy.py` (v0.30.0)
The policy block's shape, defaults, validation and resolution — required → deny → allow →
default, with area rules scoped to phases in progress. The required set (audit's own commands,
skills and agents, which no policy can deny) is read off the plugin's own directory rather than
listed. `validate-config.py` delegates to `validate_policy` here; `panel-server.py` and
`audit-doctor.py` call `resolve` here. `--selftest`.

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

**`PATH_PREAMBLE` is the block every other `.py` under `scripts/` carries**, byte
for byte, after the stdlib imports and above the first sibling import. It walks UP until it
finds the directory containing `_output.py`, so it encodes no depth and terminates at the
filesystem root with a named `ImportError` rather than looping; then it imports `_output`
and calls `install_path()`. `path_preamble_violations()` COUNTS rather than testing
membership (a doubled preamble is as wrong as a missing one), and it counts the block's
**lines** as well as the block — each line of it must occur once. Lines rather than the
block alone is F94: a file that pastes the preamble once and then repeats only its
`import _output` / `install_path()` tail carries the TEXT once and bootstraps TWICE, so a
count of the whole block read the files under `panel/` doing exactly that as compliant
while the house rule said this function counted the preamble "once, never twice". It also
AST-checks that `install_path()` runs above the first sibling import — a preamble below
the imports it exists to enable is decoration. `_output.py` is exempt by name, for two
reasons: it *is* the marker, and it holds `PATH_PREAMBLE` as a string, so a text count over its own source
would read as compliant.

**`ui_surface_digests()` answers which files a surface's pictures are OF** (F85), and it lives at
the anchor for the same reason the kept-files walk does: two readers at two layers, and a copy in
either would be the second implementation of "which files" that F85's round exists to remove.
`_refs.screenshot_capture_drift()` at layer 1 holds the rule; `tools/capture-screenshots.mjs`
asks over a pipe and records the answer beside each image rather than computing its own. Membership
is **derived from the filing convention** by `ui_surfaces_of()` — `panel/`, `panel-css/`, `report/`
and `report-css/` name their surface, `panel.html` names it in its stem, `shared/` ships in every
one — so a part added under an existing directory is covered the day it lands, and a directory the
convention cannot place is **reported** rather than dropped, because a part no digest covers is a
part whose change no picture could ever be red about. The digest is over raw bytes with each member
framed as `name length` (git's own framing, so two parts cannot trade contents unnoticed) and it
includes `_ui_theme.py`, which is outside `ui/`: `TOKEN_CSS` heads the report's stylesheet and is
substituted into the panel's, so a palette edit moves every picture. `_panel_ui.py` and
`_report_ui.py` are deliberately out — they carry part order and the tag wrappers, both already
pinned by name in their assembly suites, and admitting them would oblige `_report_html.py`, then
every module that emits markup, then the fixture manifests, at which point every commit reddens
every picture. The **renderer is the stated limit** of this rule, not an oversight. Three shapes
return an error with the digests left empty rather than a value over what remains: a tree that
cannot be walked, a tree with no part in it, and a surface holding nothing but `shared/` — all
three are how a renamed directory presents, and a digest over the remainder would be stable,
comparable and about a tree that is not there.

**`prose_number_claims()` is where this repo's most frequent defect goes to die.** A number
written into prose rots, because nothing compares it to the thing it describes — F29, F39 and
F43 are all one bug, and every earlier response was to correct the figure, which buys one green
day. Three families of present-tense claim are recognised, and none was adopted before its
sites were counted and checked — an extension that fires on forty correct lines is worse than
no extension. What each measured on the day it landed: **cardinality** (`its N cases`) found
51 sites, 9 already wrong; **persistence** (`` `NAME` stayed at N ``) found 2, both already
wrong — that is F43; **completeness** (`all N of them`, `all N … have`) found 4, 3 already
wrong. Re-derive any of them by breaking the check, never by reading this. All three take the same
remedy — **delete the number** — and the evidence for choosing that over "make it carry its
basis" is `CONTRIBUTING.md`, whose files-over-500 figure *does* name a command that prints it
and rotted in both halves anyway. A basis makes a claim checkable; only deleting the number
makes it un-rottable. Every property below is designed in and pinned by its own case: no
regex (this module carries `ast`, `os` and `sys` only, and hooks import it on every tool
call); history stays writable, so `stood at N` and `was still N` are legal and `stayed at N`
is not; a number carrying its own re-derivation is allowed, and the basis is read across a
line wrap because every document here is hard-wrapped; and the repair must itself read clean,
or the lint forbids its own remedy. F59 added one more: the number may be written as
a **word**, and `_numeral_span()` reads both spellings for every shape so there is no second
grammar to drift. Its table stops below `ten` on a measurement, not on taste — under `ten` a
written-out number in this tree is a determiner, a pronoun or an anaphor pointing at an
enumeration in the same breath, and the shapes cannot tell that from a count. What it cannot
see is written down with its direction — a count spelled as one of the small words that table
leaves out, claims split across a wrap, completeness with no auxiliary, persistence naming no
code in backticks, and a numeral written with an interior separator, which is a ratio or a
measurement and not a count of things — and every one of those is an **under**-count, which is
the quiet direction, so a clean result means "none of the known shapes", not "no claims".

**WHERE it looks is derived, and that was the other half of the same defect** (F64, F71). The
scanned set was a hand-written pair — `.py` under `hooks/` and `scripts/`, plus three named
documents — so a claim in `tools/`, in `tests/`, in `scripts/ui/*/README.md` or in the plugin's
own product documents was written where nothing read it, and that is where the claims had gone:
a part count per assembled surface, a suite size per boundary docstring, a file count in the
prover. It is now every `.py` and every `.md` this repo keeps, walked off `.gitignore` because
these suites are verified over a `git archive HEAD` export with no `.git` in it, and a file
added to the repo is scanned by default. Excluding one is a row in
`_output.PROSE_SCAN_EXEMPT` carrying a reason a reader can disagree with — released history,
a dated design record, a generated document, and the two suites that hold this scanner's own
fixtures. A case checks each row's premise rather than its presence: the path exists, or
`.gitignore` names it.

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
the build on any document that states the rule and then carves an exception out of it.
`doc_prose_numbers()` runs `_output`'s prose-number rule over every `.md` this repo keeps — the
derived set described under `_output.py` above, product documents included — and it **delegates**
to `_output._prose_number_claim` rather than restating the shapes, because a second copy of the
pattern would be precisely the defect both scanners exist to catch; a case asserts there is no
second definition. `_PROSE_DOCS` survives as the three documents that were once the whole list,
and it is now a BLINDNESS check: each claims to be a definition of how this repo works, so a
derivation that stopped reaching one has gone quiet rather than clean — which is the direction a
floor derived from the walk itself cannot see. `navigability_violations()` and `ui_navigability_violations()` both **name** an
asset they could not read and a directory they could not list, rather than skipping it (F44): the
`.py` side had reported a file it could not *tokenize* since F21 while quietly swallowing one it
could not *open*, and the `ui/` side returned an empty list for a missing `scripts/ui/` — the whole
report and panel UI gone, printing exactly what a clean tree prints. `--selftest`.

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
basename still exists anywhere in the plugin, and `sweep_glob_drift()` holds every document
that shows the selftest sweep to the RUNNER — scoped to the runnable region, so the places
this guide writes the flat glob as prose stay legal. That sentence said "the recursive `find`
form" for a while after the runner replaced it, and named a count that had since grown: two
rotted claims about one rule, in the file that documents it.

`sweep_doc_drift()` is the other half of the same rule, and it judges the LIST rather than the
documents in it. `SWEEP_DOCS` is hand-written, so until this existed a new document telling a
reader to run the retired glob was green twice over — never opened by the check, and read by
nothing else. It walks every document of a format `_runnable_text` has a rule for and reports
one that teaches a sweep without being listed. Its candidate set is DERIVED from `.gitignore`
rather than hand-pruned: `.claude/worktrees/` holds whole checkouts of this repo, so a scan
that walked them would report every sweep document once per recent agent — a finding count
that depends on nothing in the commit. A derivation is only as good as its pattern, so the
rule also reports the blind direction, a listed document the walk can no longer reach. This
file is an anchored surface itself, and its own fixture paths are BUILT rather than spelled
for that reason.

That walk is now the only one: `raw_url_pin_drift()`, which holds a published `curl` to a
TAG rather than to a moving ref, had a prune list of its own — a handful of directory names
— and it was wrong in both directions at once. It reached whatever the browser tool had last
left in the tree, so its candidate set moved with what had lately run on the machine rather
than with the commit, and it pruned `.claude/` wholesale, which held the repo's own tracked
skills out of a rule that is precisely about a document telling a reader to fetch something.
It also carried an exemption against the `EXCLUDED` table that compared a path string with
`(path, reason)` pairs and so could never fire: the fence scope is what spares `CHANGELOG.md`
quoting a dead URL as history, and a case now pins that it is the scope and not an exemption.
The remaining edge is stated rather than papered over — `.gitignore` is read for DIRECTORIES,
so a file it ignores of a scanned format stays a candidate, and for this rule that is the
rendered report, which is generated and can carry a fence.

`doc_link_drift()` rides the same walk and asks the question nothing here asked at all:
**is a document reachable?** No rule enumerated the root-level documents, none counted them,
and none checked that one is linked from anywhere — there was no Markdown link checker in the
tree. A document nobody links to is a document nobody reads, and it fails with every gate
green. That became load-bearing when the documentation was split by audience, because the
split's whole value is that a new reader's path to first success is short, and a path is a
property of the link GRAPH rather than of any one file. Two directions, asymmetric on purpose:
every inline link the walk can reach is resolved against the directory of the document that
wrote it — a claim about a file is checkable wherever it is written — while only *root-level*
documents are required to have an inbound link, because reachability is a property of the
published root and demanding one for every `SKILL.md` would need a blanket exemption. The
entry point is a constant rather than an exemption, and `UNLINKED_BY_DESIGN` is checked in
both directions like every other declared exclusion here: an entry that has stopped being a
root document, or that something links to after all, is a finding rather than a row that
quietly excuses nothing. Reference-style links and autolinks are not resolved, so it
under-reports rather than over-reports — the same limit this module's header states about a
path split across two literals.

`tool_basename_drift()` covers the shape none of the above can see. `tools/` never spells a
route: it says `resolveScript('panel-server.py')`, so there is no `scripts/…py` on the line for
a per-line rule to match, and the reference fails at RUN time — when someone drives a browser —
instead of at lint time. The rule is therefore about the NAME: a `.py` basename literal
anywhere under `tools/` must name a file that exists. **What it catches is a rename or a
deletion; what it does not catch is a MOVE**, and that division of labour is deliberate rather
than a gap — a tool that resolves by basename is genuinely unaffected by a move, so only the
resolver covers that half and only the lint covers a name that stopped existing. Both halves
are cased, including the one asserting the move stays green. The four trees it accepts a name
from include `tests/` and `tools/` themselves, because a tool's usage line names itself and a
docstring names where its behaviour is pinned; excluding them would make every usage string a
violation, and a lint that cries about correct code is one somebody switches off.

Its one exception table, `TOOL_FIXTURE_BASENAMES`, is for a name a case must WRITE with the
Python extension because the scanner under test opens nothing else. **A name a case only talks
about is spelled around rather than exempted** — drop the extension where nothing reads it,
borrow the JavaScript module one where the rule under test cannot tell the extensions apart, or
assemble the literal from pieces where that shape *is* the fixture — and the function's
docstring names the file in `tools/` that does each. A fixture nothing creates is
indistinguishable from a reference that has gone stale, so an exemption class for it would be a
place to declare away the defect the rule exists to find. Until F68 the convention existed only
as a lint failure: an hour every new author pays once, and it had been paid before it was
written down.

`artifact_version_drift()` (F12) asks the same question of a COMMITTED PAGE rather than of
prose. A rendered report stamps the plugin version that produced it, so a report in the tree is
a published claim about which release the reader is looking at — and the scale demo under
`docs/` served a stamp several releases behind the plugin while every check over it stayed
green, because they asserted **content**: no invalid-manifest banner, a usage section
present. Content is what does not change with a release, so content assertions cannot see
age. The rule compares each stamp with `.claude-plugin/plugin.json` and names **both** versions,
which is what a byte comparison cannot do. It also **discovers** the pages rather than listing
them: `tools/check-rendered-artifacts.py` re-renders and compares bytes, and its own docstring
names the artifact nobody listed as the direction it cannot cover, so a table here would be a
second copy of that same blind spot. A tree where nothing is stamped is itself a finding —
without that, a renamed class would take the rule quiet instead of red, and the panel's
template is in the candidate set carrying no stamp precisely so a case can tell the two
apart.

`screenshot_capture_drift()` (F62) asks it of a PICTURE, which is why it cannot be answered the
same way. The panel paints its own version in the topbar and every shot starts at the top of the
page, so each committed PNG under `docs/screenshots/` claims a build — and reading that claim
back means reading text out of an image. `tools/capture-screenshots.mjs` refuses to compare
these pixels at all: F18 settled that, and its header declines three repairs by name, including
masking the topbar box ("a promise never to see drift in the most-looked-at part of the page")
and writing a fake version into the picture. So the basis is recorded beside the pictures
instead, by the run that took them — `docs/screenshots/captured-at.json`, one entry per image
carrying the version and the hash of the bytes it was written as — and this rule compares it.
The record is not a guess: the panel leg asserts the LIVE topbar names `plugin.json`'s version
before any shutter opens, so the sidecar writes down what was already checked. Per file rather
than per run, because `--only report` rewrites some images and leaves others, and a run-level
version would then claim the new build for pictures nobody re-shot. The hash is what stops the
sidecar being edited into agreement without the pictures being the ones captured; it does not
make the claim unforgeable, only impossible to break by accident. `demo-gate.gif` is out of
scope on purpose — `tools/capture-demo-gif.py` writes it, so demanding an entry would report a
missing basis against a producer never asked to record one.

**That version answered only half the question, and F85 is the other half.** "Was this captured
at this release" is not "does this picture still show the current UI", and the difference was
live: commits landed under `scripts/ui/` after the last re-capture, the recorded version was
still current, and this rule was green over pictures of a panel that had since moved. Pixels
cannot close it — F18 settled that — but the UI's **sources** are committed bytes, so a digest
over them is host-independent by construction where the rendered page, which paints the project
path, is not. Each entry therefore also carries the **surface** it is a picture of and the digest
of that surface's sources, from `_output.ui_surface_digests()` described above, and
`_ui_source_findings()` compares it. **Per surface**, which is what makes it a rule rather than a
nuisance: a report-only change reddens the report's pictures and asks for none of the panel's
back. The surface comes off the **entry**, written by the leg that opened the shutter — never
inferred from a `panel-` prefix, which would be a second opinion about which surface a picture is
of, held by a naming habit rather than by the code that took it. An entry with **no** digest is a
finding and not silence: absence is not agreement, so the rule is red until a capture has written
one, and the repair is the capture rather than a default filled in here. The digest comparison
runs **after** the version comparison, because both repairs are the same command and one finding
per picture is what a reader can act on.

`--selftest`.

### `plugins/audit/scripts/usage/_usage_core.py`
The arithmetic the whole metering stack stands on, and nothing else: the `DEFAULT_PRICING`
table plus `rates_for`/`price`, one ISO parser and one hour-bucket rule, the roll-ups
(`totals`, `aggregate`, `aggregate_area`, `rows_for_area`, `heatmap`) the CLI, the report and
the panel all read, and — since U3.2 — the three readers every analytics pass starts from
(`task_index`, `_tokens`, `_cost`). Values in, values out — no file, no process, no transcript
— which is why its cases need no fixture directory. `pricing_divergences()` lives here too:
`hooks/_config.py` must price a model with no config present and may import nothing from
`scripts/`, so its copy of the 13 x 5 rate table is deliberate and the `pp` cases are what
keep the two identical.
`--selftest`.

### `plugins/audit/scripts/usage/_usage_spend.py`, `_usage_economics.py`, `_usage_routing.py`, `_usage_coverage.py`
What the ledger MEANS, as `rows -> dict` functions. One file until v0.40.x, when it reached 955
lines and was cut on its own section markers (U3.2) — every body moved by line range, so each
module does exactly what its section did:

* **`_usage_spend.py`** — `series`, `compare`, `cache_profile`. A first-run dashboard has no
  prior window and must not invent a "+100%", and a cache profile reports RATES rather than a
  "you saved $N" nobody can check. `series` folds its tail past `MAX_SERIES` because the
  categorical palette is only validated to eight slots.
* **`_usage_economics.py`** — `unit_economics`, `cost_bands`/`band_of`, `phase_budgets`,
  `retry_cost`. The projection is suppressed below its sample gate and is a p25-p75 RANGE when
  it speaks; an absent phase budget renders as nothing rather than 0% or 100%; retried and
  blocked spend are reported apart and never summed into "waste". `COST_BAND_PARAMS` is the one
  statement of the relative basis's shape — `panel-server.py` serialises that exact dict into
  the page so `panel.js` cannot restate it differently.
* **`_usage_routing.py`** — `routing` and its advice. Cost per completed task per model WITHIN a
  risk band, never a bare spend-share ratio, and advice only where this repo's own evidence
  supports it: enough tasks on both models in that band, no worse mean attempts, real rates on
  both sides, and a saving clearing both a percentage and an absolute floor.
* **`_usage_coverage.py`** — `coverage` and `monthly_activity`. How much spend the attribution
  layers resolved (a dashboard that is 90% `unattributed` says so), and the ONE computation site
  behind the 12-month overview's three surfaces.

All four sit at layer 2 and read `_usage_core` and nothing else — which is what lets
`usage_ledger` (layer 3) import all four for its re-export. The three readers they share
(`task_index`, `_tokens`, `_cost`) went DOWN into `_usage_core` rather than into a shared layer-2
base, because a layer-2 module may not import a peer. `--selftest` on each.

### `plugins/audit/scripts/usage/_usage_bench.py`
The `--bench` mode of the four modules above, and the fixture it runs them on: a computed plan
and `n` deterministic rows, timed best-of-N at 1k / 10k / 50k so the interesting property (the
SHAPE of the per-row cost) is visible rather than a single number. It prints; it never fails —
a shared runner's noise floor is wider than the regressions worth catching, and a gate that flaps
teaches people to ignore it. It opens no file, so it can neither read nor grow this machine's own
ledger. It sits at layer 3 rather than beside the passes because it calls all four of them, and
`render-report.py --bench` loads it through `_loader` for `_time_best` so that the two benches in
this tree share one definition of best-of-N. `--selftest`.

### `plugins/audit/scripts/usage/usage_ledger.py`
The token-usage metering core `meter-usage.py` and `audit-usage.py --backfill` both call.
Claude Code hands hooks a `transcript_path`, not token counts, so this reads the transcript
JSONL directly — `message.usage` alongside `message.model`/`timestamp`/`gitBranch`/`sessionId`,
plus each subagent's sibling `subagents/agent-<id>.jsonl` + `.meta.json`. The one correctness
trap it exists to close: a single `message.usage` block repeats across every transcript entry
sharing a `message.id`, so naive summation overcounts spend by roughly 2.4x — this module dedups
by `message.id` within and across scans. Attribution runs task -> phase -> window ->
unattributed, highest precision first, nothing ever dropped. The layer beneath it (`_usage_core`)
was split out when the file passed 2,600 lines, along with the analytics that are now four
modules, and every public name those five define is RE-EXPORTED here: nothing imports this
module by name — every
consumer loads `usage_ledger.py` by path and reads attributes off the module object — so the
module object has to keep serving all of them, and the `rx` cases assert it does.

### `plugins/audit/scripts/governance/_journal_io.py` (v0.29.0)
The trail itself (layer 1): `journal_dir`, `read_file`/`read_all`/`journal_files`,
`append(project, entry) -> path|False`, `verify`, and the row/hash vocabulary underneath
them. It sits at the bottom because two modules that are not commands need it — `_help`
(layer 3) normalises one row to show a reader what a row looks like, `audit-doctor` reads
and verifies — and because `hooks/_config.py` asks it for `journal_dir` on every tool call,
where executing an argument parser and four subcommand bodies to resolve one path is cost
with no caller. Three of those reaches were `_loader` loads of `audit-journal.py`; the
fourth, `_panel_state`'s, was the edge `_deps` deliberately could not see (it spelled
`script_path()` on one line and `load()` on the next) and is now an ordinary import.

### `plugins/audit/scripts/governance/audit-journal.py`
The CLI over `_journal_io`: `append | verify | show | archive`, turning the library's dicts
into printed lines and an exit code (0 healthy, 1 the chain does not hold, 2 usage).
One file per writer per month (`<journal dir>/<YYYY-MM>.<writerId>.jsonl`, default beside the
manifest) so parallel worktrees never conflict; each row carries `{v, ts, actor, action,
target, summary, stateHash, prev, hash}`, sha256 over canonical JSON, with the first row's
`prev` derived from the file's own base name so a file cannot be renamed into another
writer's slot. `verify` reports an edited / deleted / reordered row as a FINDING (exit 1) and
a torn tail or out-of-band drift as a WARNING (exit 0). **Tamper-evident, not tamper-proof** —
stated in the module, the README, the panel's own Settings card and SECURITY.md, because a
forger who rewrites the whole file still verifies. `append()` never raises. `--selftest`.

### `plugins/audit/scripts/demo/gen-demo-manifest.py`
Generates the synthetic LARGE manifest fixture behind `docs/demo-large.html` and the panel
screenshots, on demand instead of committing it — the same flags always produce the same
bytes, so CI builds it, captures from it, and discards it, and nothing drifts the way the
uncommitted original did. `gen-demo-manifest.py <out-dir> [--phases 50] [--tasks 20] [--seed
11] [--single-file]` deliberately carries every state a reader can filter on (all phase/task
statuses, `blockedBy`, `dependsOn`, budgets over/under, `area` tags, a full bug lifecycle),
deterministically (fixed seed, no wall-clock) and validator-legal by construction (a `done`
phase never contains an unfinished task). `--selftest`.

It also writes the **evidence ledger** beside the manifest and points the plan at it:
`generate()` stamps a `testEvidence` block on every subject that has a recorded run, and
`write_manifest()` writes the rows those pointers name — through `_evidence_io.row_for`, so a
demo row is spelled by the recorder rather than by a second opinion about what a row is. The
plan and the record are written together for one reason: a pointer whose `runId` no row
answers to renders as `Pointer without evidence`, and the demo is the one page that state must
never reach by accident. `generate()` itself still writes nothing — the rows are a value it
returns none of, and `write_evidence()` is the only part that meets a disk.

**The fixture is a mid-flight adopter**, which is what makes the evidence boundary visible in
what ships. `_pre_recorder_phase()` holds the first finished phase back from the run plan, so
nothing in it carries a pointer; `_stamp_since()` then derives `meta.evidenceSince` off the
remaining rows through the recorder's own `_evidence_io.since_from_rows`, and the subjects behind
that moment render `Before recording` rather than `No evidence`. It is held back only when a
later phase still records — a fixture with no runs at all would name no boundary and take the
ledger, the pointers and every state that depends on them down with it at the smallest sizes.
`SCHEMA_EXEMPTIONS` used to hold the key back on exactly this argument, and that row is gone.

### `plugins/audit/scripts/demo/gen-demo-usage.py`
Generates a synthetic usage ledger consistent with a real manifest — task/phase ids that exist,
timestamps inside each task's own `startedAt`/`completedAt` window — so the report's Usage
section (and its screenshots) show something worth looking at instead of the empty state a
manifest with no spend produces. `gen-demo-usage.py <manifest> [--out-dir DIR] [--seed N]
[--authors a,b,c] [--adhoc-days N]` is deterministic (fixed seed, no unseeded random) and maps
a manifest's illustrative model tier to the concrete ledger model id the runtime actually
records. `--selftest` pins determinism and referential integrity against the manifest.

### `plugins/audit/scripts/demo/_demo_cast.py`
Three fictional `.example` identities (layer 1), and the smallest module in the tree. Both
demo generators must attribute to the SAME people: `gen-demo-usage.py` stamps them on every
synthetic ledger row and `gen-demo-manifest.py` hands them out as `meta.areas[*].owner`,
precisely so the shipped demo shows `/audit:doctor`'s owner-versus-ledger join succeeding.
`gen-demo-manifest.py` used to read the tuple off `gen-demo-usage.py` through `_loader` —
one entry point loading another for one name, the last of the seventeen
`KNOWN_LAYER_DEBT` edges. The alternative to a small module was not a bigger one; it was a
second copy of three addresses that nothing would ever compare.

### `plugins/audit/reference/manifest-conventions.md`
Shared conventions every command reads first (lives OUTSIDE `commands/` so it can't register
as a command): manifest path resolution, the Edit-and-revalidate rule, id allocation
(task `<phase>.<n>`, bug `BUG-<n>`, bugfix phase `BF<n>`), status enums, new-task/new-phase
templates, fileIndex maintenance, done-phase immutability.

### `plugins/audit/scripts/manifest/_manifest_rules.py`
The referential rules, run after every manifest mutation — the checks the JSON Schema
can't express: unique ids, resolvable `blockedBy`/`dependsOn`, dependency **cycles** (incl.
task-blocked-by-own-phase deadlocks), **bidirectional** `fileIndex ↔ task.files` integrity,
`bugs[]` shape + **reciprocal** `bug.taskId ↔ task.bugId` cross-links, enums,
`check_ado_meta`, plus non-fatal WARNINGs for unknown/typo'd keys (did-you-mean) and pre-0.3
status combinations. `validate(manifest)` is pure: parsed JSON in, `(findings, warnings)`
out, never raises, no I/O, no module state. It sits below every consumer because FOUR
modules need it and only one is a command — `_panel_state`, `audit-doctor`, `audit-status`
and `migrate-manifest` all used to load `validate-manifest.py` through `_loader`, four of
the seventeen `KNOWN_LAYER_DEBT` edges.

The file itself is now a fraction of the 1,406 it was cut from, and holds **two** things:
`_check_meta` (the document's header — the root key vocabulary and `meta`, which need
nothing the walk builds) and `validate()`, which decides the **order** the pieces run in.
The order is the one thing that could not move into a piece: `_walk_phases` builds the index
the five checks after it read, so it runs once and first. Everything else is one of the five
modules below, each re-exported here as a thin alias so no consumer had to learn a new
import; a case pins every alias with `is`, so a pasted-back copy fails by name. It moved
**layer 2 → layer 3**, which is the whole structural cost: the four pieces sit at layer 2
above `_manifest_vocab` at layer 1, and a consumer AT layer 2 is still not strictly
downward.

### `plugins/audit/scripts/manifest/_manifest_vocab.py`
The manifest's **words** (layer 1), and the four shape checks every level of it shares.
The status/tests/risk/bug enums, the `BUG-`/`PROP-` id patterns, the known-key set per level
(root, `meta`, `meta.ado`, phase, task, bug, proposal), and `_unknown_keys`,
`_require_fields`, `_safe_list`, `_strip_line_suffix`, `_check_ado` — asked of a phase, a
task and a bug alike. It holds **no rule** and reaches nothing but `_output`, which is why
it can sit at the floor where all four layer-2 pieces import it; a vocabulary copied into
four files is four vocabularies that disagree the first time one learns a word. `TERMINAL`
is deliberately **not** here — it is `_manifest_io`'s, and holding it would put this module
at layer 2 and its consumers at layer 3.

The `KNOWN_*` sets restate vocabulary `schema/audit-plan.schema.json` already owns, and they
are now **checked against it rather than trusted**. `SCHEMA_ANCHORS` records where each set
lives in that document, spelled as the dotted path `_help.fields()` produces
(`phases[].tasks[]`), and `OFF_SCHEMA` records the keys that deliberately have no
schema counterpart — legacy names v0.3.0 removed, plus `meta.workspaceRoot`, which
`reference/orchestrator.md` still names as the pre-0.6 fallback for `gitRoot` — **one written
reason each**, because an exemption list without reasons is where a lint goes to die.
`_help.schema_vocab_drift()` is the comparison and names what disagrees: a schema property no
set holds, a set key neither the schema nor `OFF_SCHEMA` accounts for, an anchor that resolves
to no properties at all (a renamed `$def` would otherwise make that level a comparison against
nothing), a `KNOWN_*` set nothing anchors, and a stale or reasonless exemption. It is a
**lint, not a derivation**: the sets are deliberately WIDER than the schema, and derivation can
express "equal to" but not "wider" — see the `SCHEMA_ANCHORS` comment for that argument and for
why the comparison had to live with the walk, a layer up.

### `plugins/audit/scripts/manifest/_manifest_phases.py`
The **one walk** over every phase and every task (layer 2), and the three checks it makes on
the way. `_walk_phases` visits each object once and returns a five-key **index**
(`phase_ids`, `task_ids`, `task_by_id`, `task_files`, `bug_links`) that every check in
`_manifest_crossrefs` then reads — naming that index is what let the walk be cut out at all.
It stays one pass on purpose: splitting it per-question would visit every task four times
and would let two of them disagree about which objects were skipped as malformed. Also the
per-phase rules a schema cannot express — a parallel-run `claim` left on a finished phase,
an `area` that normalises to no tags at all, a `budgetUSD` of zero, and a phase marked done
over tasks that are not **finished** (done *or* cancelled).

### `plugins/audit/scripts/manifest/_proposals.py`
The proposal lifecycle itself (layer 4): the refusals in `commands/propose.md`'s own order,
the id allocation that counts live AND still-parked ids, the collision remap, the dependency
closure, `plan_for`, `run()` — which takes the index lock, applies, revalidates and writes —
and `proposal_rows`/`list_view`, the READ side.

**The read side is part of the rule, and it took F91 to notice.** `list` was the one verb no
script produced: `commands/propose.md` specified a table and a model rendered it from that
prose, so what a user got was whatever the model recalled — an accurate summary, and no table.
Meanwhile the panel derived its own rows in `_panel_composition`, with a `_parked_blockers`
walk answering the question `unresolved_refs` already answered. One derivation now, two
renderings: cards in the panel (`_panel_state` binds `_proposals_view` to it), a table on the
command line. `list_view` also carries `hidden` and `phaseCount`, because an empty list means
different things in a plan that has phases and one that has none, and a renderer that had to
go back to the manifest for that would be its second reader.

**Why a module and not just the script.** It was one file until the panel became a second
caller. The panel's write path sits BELOW the entry points, so a panel reaching up to a command
is an edge pointing the wrong way, and `_deps.layer_violations()` said so by name rather than
leaving it to taste. The split is the same one `check-ado-item.py` has over
`_ado_conventions.py`: a door and a rule.

**Orchestration is part of the rule.** `run()` locks, applies, revalidates and only then
writes — a caller that had to remember to lock, or to refuse a result the validator would
reject, is a second chance to get it wrong. Revalidation happens BEFORE the write, so a
manifest that would be invalid never reaches disk and a refusal leaves nothing half-applied.

**It never asks anything.** `plan_for` reports what a materialization would pull in and `run()`
refuses while the answer is undecided, because a rule that stops to interview cannot be called
from an HTTP endpoint, and a rule that guesses is worse than one that refuses.

### `plugins/audit/scripts/manifest/materialize-proposal.py`
The proposal lifecycle, as a script instead of as prose (layer 7). `commands/propose.md`
specified all of it and executed it by reading itself, which was fine while that command was
the only caller. The panel can materialize and drop now, and two readings of one rule are two
answers the first time either is edited — so the rule lives here, with cases, and the command
became a thin caller.

**Plan, then execute.** `plan` writes nothing and reports exactly what would happen, including
the dependency closure. That output is what the command's confirm and the panel's dialog both
render, so a human sees what a materialization pulls in **before** anything is written. It is
also why the dependency decision is a FLAG (`--with-deps` / `--drop-edges`) rather than a
question asked inside the script: a script that stops to interview cannot be called from an
HTTP endpoint, and a rule that guesses is worse than one that refuses. Undecided is refused
and names what it is waiting on.

**The closure is dependency-first**, because materializing a phase whose blocker is still
parked writes a manifest the validator refuses. A cycle terminates rather than recursing — the
validator reports the cycle, and a diagnostic must not hang on one.

**The collision guard remaps inside the payload only.** A parked payload reserves its ids, so
normally its phase id is free; when it is not, the next free `P<n>` is allocated counting live
AND still-parked ids, and the payload's task ids and intra-payload refs move with it. An edge
pointing at a live phase is left alone: rewriting it would silently repoint real work.

**`list` prints its table here** (F91), for the same reason the other three verbs live behind a
script: it was described in prose and rendered from prose, so nothing checked it and a user
asking for the list got a summary instead. `LIST_COLUMNS` is `propose.md`'s own column order,
measured across the header and every row at once so the columns stay columns; a proposal with no
payload renders `-` in the payload column off `hasPayload` rather than off a falsy `phaseId`;
and the empty render says which empty it is — history hidden by the default filter, and whether
there is a plan at all — because the two need different advice. `list` never takes the index
lock, which is why it does not go through `run()`.

**Drop needs a reason, revive keeps it.** `notes` is required once a proposal is dropped —
the validator enforces it rather than trusting this command's prose to have asked — and
`droppedAt` is its timestamp, the counterpart of `materializedAt`. Reviving flips `dropped`
back to `proposed` and leaves the reason as history: a revived proposal that forgot it was
ever declined has lost the only thing the archive was for. A materialized proposal cannot be
dropped, because its phase is live and the record is the history trail.

### `plugins/audit/scripts/manifest/_ado_connect.py`
Every decision `/audit:sync connect` makes on the way to a first working connector (layer 1).
Four rungs, each with its own stop: which **transport** is available, which **auth path** is
in effect for this organization, what a read-only **probe** proved, and which **process** the
board runs.

**Why the feature exists.** The connector was the first thing a new person on a team touched
and the only part with no guided path — install the extension, authenticate, work out which
auth path is actually in effect, hand-write `meta.ado`, and only then discover whether any of
it worked, because the first thing that *proved* access was a `push`, which is also the first
thing that can CREATE items on somebody's real board.

**Everything arrives as an argument**, which is what puts it at the floor beside `_ado_parent`
and `_ado_conventions`. That is not tidiness: it is the only shape in which the *stopping*
rungs are reachable from a test, since each of them describes a machine that has no `az`, no
credential or no board.

**Credentials are counted, never read.** Rung 2 answers "which path" from three things that
are not secrets — whether an environment variable is SET (never its value), the Azure sign-in
`az account show` prints, and the list of organizations `az devops login` has stored a PAT for,
which is a file of organization URLs with no token in it. The plugin's own `guard-secrets-read`
hook exists to block the other move.

**And where it cannot tell, it says so.** Two auth paths can be present at once — measured on
the machine this was written on, where one organization resolved through a stored PAT and
another through the Azure sign-in at the same moment — and nothing observable from outside says
which one answered. So more than one present path is reported as ambiguous *by name* rather
than resolved by a precedence rule this module cannot verify. The fact that holds either way is
the trap the rung exists for: a board command that succeeds proves the ORGANIZATION is
reachable, never which identity reached it.

**The type is the discriminator, not the states**, and that came from measuring both lab
boards rather than reading the process documentation. The Agile board carried `User Story`
with only `New` and `Closed` in use, because no item was sitting in `Active` or `Resolved` —
so observed states are evidence and never proof, and every message built on them says which
of the two it is. `types` is a per-process table for the same reason: Basic has no `Bug` type
at all, so a proposal built from "Bug unless we saw otherwise" would configure a connector
that cannot file a bug.

**No expiry date, deliberately.** Neither transport can be asked when a credential expires — a
PAT's expiry needs the token itself or an organization-admin scope this connector never
requests — and a key holding a date nothing can supply would be printed as `null` by every
surface and read as "does not expire" by every reader. What `meta.ado.connection` records
instead is which auth PATH was in effect the last time access was proven, which is what turns
a later 401 into an expired token rather than a broken configuration.

### `plugins/audit/scripts/manifest/ado-connect.py`
The door onto `_ado_connect` (layer 7), the same shape `check-ado-item.py` has over
`_ado_conventions` and for the same two reasons: a `python3 -c` one-liner naming a source path
is what `guard-secrets-read` refuses, and the rule belongs somewhere it can be tested.

**Read-only, and the write is somebody else's.** Every rung reports; nothing here edits the
manifest. Step 5 is a *plan* — set / keep / change, per key — that the orchestrator confirms
through `AskUserQuestion` and applies itself, then revalidates. A `change` row is offered and
never taken: the value already in the file may be the one a person chose against this
command's advice.

**The board call is the caller's.** `az` is never run against a board here, because the
session may be holding MCP tools this file could never call. Rung 3 grades an ENVELOPE the
caller writes after making the call it chose — `{exitCode, stderr, rows}`, one shape for
success and failure both, which is also what makes the failure branch reachable from a test.

**Two measured error shapes, and the one that misleads.** `az boards query` against a project
that does not exist says "The project specified is not found in hierarchy" — the credential
worked, the name is wrong. Against an organization that does not exist it says *"you need to
run the login command"*, identically to a genuine credential failure. So that text is graded
as one verdict naming both readings; telling somebody to log in again when their organization
name has a typo in it is the kind of wrong answer that costs an afternoon.

**`observe()` is the only part that touches the machine** — a PATH lookup, an extension list,
a sign-in read and a file of organization URLs — and it is separated from `report()` for the
testability reason above. Its suite pins that seam, so stubbing it cannot quietly become a way
of testing a path production never takes.

### `plugins/audit/scripts/manifest/check-ado-item.py`
The gate `/audit:sync push` runs an item through **before** it creates it (layer 7).
`_ado_conventions` holds the rule; this is the door the orchestrator knocks on, and it is a
real command rather than a `python3 -c` one-liner for a reason that is not style: a one-liner
naming a source path is the shape `guard-secrets-read` refuses (F20/F22), so the check would
be blocked on exactly the machines that need it.

**A guard, not an advisory.** `SECURITY.md` splits the two — advisory paths fail open, guards
fail loud — and a work item that lands on someone's board looking foreign cannot be
un-landed. A violation is exit 1 and the caller stops. Exit 2 covers unreadable input, so a
manifest that cannot be parsed never falls through to "conforms".

**Two zeroes that must not read alike.** A board with no `meta.ado.conventions` exits 0
because there is no standard to meet, and it *says* so ("nothing was checked") rather than
printing the clean message; `--json` carries the same distinction as `hasStandard`, so a
script can tell them apart too. A caller that cannot would read an unconfigured board as a
conforming one, which is the quiet failure the whole feature exists to prevent.

**`--item` and `--fetched` are two shapes and two questions** (F106), which is why they are
two flags and exactly one is required. `--item` grades a payload the connector is ABOUT to
create — work item type at the top level, a resolved `parent` beside it — and its exit 1
means *do not create this*. `--fetched` grades the rows `fetch-ado-items.py --out` already
wrote: items ON the board, with the type and the parent INSIDE `fields`, and its exit 1 is a
finding about cards somebody is already looking at, not a refusal of anything. That payload
used to be fed to `--item`, where `requireParent` read a top-level key the shape does not
have and refused items whose parent was in fact set, while the type-scoped rules silently
graded nothing at all — so `--item` refuses the fetched shape outright now and `--fetched`
translates it through `_ado_conventions.as_gradable_item`, which is the one place that says
which key holds what. Two further differences follow from *already created*:
`meta.ado.fields` is NOT merged on this path (that template is what a CREATE must send, and
merging it into a card the board already has would grade a fiction), and the worst outcome
across the rows wins, with a row whose work item type the payload does not carry taken as
exit 2 rather than folded into a conforming count — an ungraded row reported as clean is the
silent pass this command exists to stop.

**A `NOTE:` line travels beside the verdict and moves neither half of it** (F120).
`requireParent` grades the parent the connector RESOLVED, and push resolves none for a bug —
it creates that card with no parent link and names no third kind to hang — so the rule is
scoped by work item type from `meta.ado.types`, and the narrowing is PRINTED rather than
applied in silence. A board asking for a parent on every card is asking for something this
connector cannot supply, which is a sentence its operator is entitled to. Exit code and
`conforms` are untouched; `--json` carries it as `parentRuleExemption`.

### `plugins/audit/scripts/manifest/_ado_drift.py`
Who wrote a linked work item **last**, and whether pushing would overwrite them (layer 2).
`/audit:sync status` used to offer a difference two readings — our side is right (`push`), or
ADO is right (edit the manifest). On a board with several teams and several legitimate sources
of work items, the commonest reading is the third: somebody else moved this card after we last
touched it, and neither side is wrong.

**It needs no identity, and that is the design.** A push writes ADO first and the manifest's
`lastSyncedAt` second, so for a write of our own `System.ChangedDate <= lastSyncedAt` always
holds. The question is therefore not *who* wrote — the plugin does not know its own ADO
identity — but *whether anyone wrote after us*. `System.ChangedBy` rides along as information
for the reader, never as an input to the comparison. `DEFAULT_TOLERANCE_S` absorbs the skew
between the local clock that stamped `lastSyncedAt` and ADO's server clock that stamped
`ChangedDate`; without a margin our own write reads as somebody else's.

**Two orthogonal answers, deliberately not one enum.** `class` is about time (`local_ahead`,
`external_change`, `unknown`) and `drift` is about state. Collapsing them would let "in sync"
hide the fact that somebody else moved the card into the state we happened to want. The
manifest-status → ADO-state map is **not** reproduced here: it lives in `commands/sync.md`, so
`mapped` is an input, and omitting it makes a row say the comparison was not supplied rather
than imply agreement. `origin_of` answers the other half — a card this plugin created versus
one adopted through `pull` — which the provenance tag cannot, since `meta.ado.tag` is merged
onto every item a push touches.

### `plugins/audit/scripts/manifest/explain-ado-drift.py`
The door onto `_ado_drift` (layer 7), same shape as `check-ado-item.py` over
`_ado_conventions`: a real command because the caller is orchestrator prose reaching Python
through Bash, and a `python3 -c` one-liner naming a source path is what `guard-secrets-read`
refuses.

**Not a gate, and the exit codes say why.** `check-ado-item.py` exits 1 to mean "do not create
this item". There is no refusal here: on a shared board "somebody else moved this card" is
often the normal case, so a non-zero exit would label a healthy state an error and be switched
off within a day. 0 means the question was answered, 2 means the input could not be read — a
payload that is not a list is exit 2 rather than an empty table, because a table of zero rows
reads as a clean board. The caller keeps its existing confirm gate; this only makes sure that
gate is asked with the truth in hand.

### `plugins/audit/scripts/manifest/_ado_fetch.py`
Reading the linked side of a board in **one query per chunk**, with a bound on each (layer 3).
`sync.md` step 3 said "batch-fetch the ADO side" and then named `az boards work-item show`,
which takes a single `--id` and rejects a comma list. An instruction that asks for a batch and
names a per-item command cannot be obeyed, so the run looped — one CLI start-up per linked
item. Measured on the lab board, that loop cost roughly half a second an item where one
`az boards query` answered for all of them in about the time of a single `show`: a per-item
constant against a per-call one, so the gap only widens.

**Three things a paragraph cannot be held to.** The chunk size, the field list and the time
bound are values here, with cases against them, because the defect being fixed *was* a prose
instruction nothing could check. `FIELDS` is a contract and lives here only — `az boards query`
returns exactly the fields the `SELECT` names, so a field dropped from it comes back absent and
reads as *the board does not have one*; both documents point at this tuple rather than
restating it.

**The ceiling is on the WIQL text, not on a count of ids**, which is why `DEFAULT_CHUNK` is an
operating point and `WIQL_MAX_CHARS` is the invariant: a chunk sized at the boundary starts
refusing the day the board's ids grow a digit, so `oversized_queries()` measures the text every
time. `run_chunk` returns a named status and never a bare list, because "the board returned no
rows" and "the board did not answer" are different answers and only the first is safe to act
on — a hang says nothing at all, which is worse than a failure.

### `plugins/audit/scripts/manifest/fetch-ado-items.py`
The door onto `_ado_fetch` (layer 7), same shape as `explain-ado-drift.py` over `_ado_drift`: a
real command because the caller is orchestrator prose reaching Python through Bash, and a
`python3 -c` one-liner naming a source path is what `guard-secrets-read` refuses.

**A gate, unlike `explain-ado-drift.py`.** That command exits 0 whatever the answer, because on
a shared board "somebody else moved this card" is the normal case. Here exit 1 means at least
one chunk did not answer and **the payload is partial** — it names the ids it has no news about,
and a diff or a push taken from it would read an absent row as an unchanged one. Exit 2 is a
manifest that could not be read or a missing `meta.ado`. It reads the manifest through
`_manifest_io.load_manifest`, so a sharded manifest's phase-held links are planned for like any
other; `--dry-run` prints the queries without spending a call, and exits 1 when a chunk would be
refused, because finding that out before the calls is the point of printing the plan.

### `plugins/audit/scripts/manifest/read-ado-links.py`
The **manifest** side of the question `fetch-ado-items.py` asks the board (layer 7): which
items carry an `ado` link, and what ADO state each one's status means. It calls no board at
all, and it exists because `/audit:sync` was telling the orchestrator to do both halves by
hand, in prose, and prose got both wrong on a real board.

**The read has to be the loader's.** "Resolve and read the manifest" plus "count linked vs
unlinked" describes a `json.load` of `manifestPath`, and on the sharded layout that file is an
index whose phases are stubs — so the phases' links and every task's link are invisible and
come back counted as *unlinked*. Nothing errors; the number is simply smaller. The same walk
`fetch-ado-items.py` uses (`_ado_drift.link_inventory`) decides what "linked" means here, so
the two cannot come to disagree, and this module adds only the half that walk deliberately
does not carry: the item's status.

**The `stateMap` translation is code now, and this file owns the table.** It used to live in
`commands/sync.md`, which meant a reader had to apply it — and `status` step 3 was never told
to, so every drift row read `state not compared (no mapped state supplied)`. That is worse
than an incomplete table: `_ado_drift.summarize()` counts an overwrite only for a row whose
state differs, so an unstamped payload reports `0 would overwrite a change made after our
last sync` — the one number the push confirm gate exists for — on a board where the answer
was never computed. The command file now names this door and states no map of its own.

**The bug status is `_manifest_io.effective_bug_status`**, which is the half no prose reader
would have applied: a bug with a materialized fix task that is done reads `fixed` while its
stored `status` still says `open`, and a human `wontfix` beats that derivation. Translating
the stored value would map a fixed bug to `New` and then report the board's `Resolved` card
as ours to overwrite. Each row prints which of the two answered it, and a derived status is
named under the table rather than left looking like a typo.

**One card claimed twice is a tie it refuses to break.** Nothing anywhere requires a
work-item id to be claimed once — `check_ado_meta` grades the shape of an `ado` link and
never the uniqueness of its target, so an import that adopts a card somebody had already
linked by hand produces two claimants for one id. Where they mean the same state the
entry is stamped and the duplicate is still named; where they do not, the entry is left
UNSTAMPED with both claimants printed, because stamping whichever the walk reached first
would push one item's status onto a card the other one owns, out of a table that reads as
ordinary. Both invocations report it, and the count is printed at zero.

**A gate in one direction only.** Exit 1 is a `--items` payload with entries in it of which
not one could be given a state — every reading downstream then has no basis, including that
overwrite count. An EMPTY payload is exit 0 with its zeros printed: nothing was asked about,
which is a different answer from nothing could be answered. `--items` without `--out` is a
usage error rather than a preview, because a run that reported a translation and wrote no
file is one forgotten flag away from the unstamped payload reaching the drift door.

### `plugins/audit/scripts/manifest/_ado_conventions.py`
`meta.ado.conventions` — what a work item must look like to **belong** on a board (layer 1).
The connector could always write a *correct* work item and could not write a *conforming*
one, and the difference only shows on a board that has a standard: measured 2026-08-19
against a real one, whose own script enforces a description skeleton, a mandatory "Done
when", acceptance criteria on stories, tags from a closed vocabulary, and a parent. Items
without those are mechanically right and visibly foreign.

**Why this is Python and not prose in `commands/sync.md`.** The connector's writing side is
orchestrator prose driving MCP calls, which no selftest reaches — precisely how the gap
survived a live ADO gate against two empty throwaway projects. A rule in prose is a rule
held in memory; here it is a function with cases, so `conformance_violations` can be proven
red. The only thing left unproven is whether the prose *calls* it, which `/audit:doctor` can
see after the fact, because a non-conforming item on the board is evidence a check was
skipped.

Both halves live here on purpose: `check_conventions_config` grades the block someone wrote
(wrong **types** are findings, unknown **keys** are did-you-mean warnings, the line
`_manifest_ado` draws), and `conformance_violations` grades an item against it. Splitting
them would put the shape and its use in two places that could disagree. An absent block
means the board has no standard and every item conforms — not "could not check", but "there
is nothing to check".

**`tagVocabulary`'s `"*"` is a key like any other and its list restricts.** It was read for
its PRESENCE alone, so a board that wrote out which bare tags it allows got no restriction
and no warning, while the config half validated those entries as strings nothing ever
consulted — the code did not do what its own schema said. The one asymmetry is deliberate:
an empty list under a real prefix admits no value, while `{"*": []}` admits any bare tag.
That is the spelling the schema and `docs/ado-connector.md` already publish for a free-form
board, so reading it the other way would change the meaning of a manifest somebody already
wrote, which is a major release rather than a fix.

### `plugins/audit/scripts/manifest/_ado_fields.py`
`meta.ado.fields` — what this project **supplies** to a governed board's fields (layer 1), and
the half `_ado_conventions` could not be. That module grades a payload and can only *refuse*;
the connector's create payload is title, description, state, area, iteration, tags and a parent
link, so on a board whose Task really owes an Activity and an Original Estimate the honest
`conventions` block gated out every CREATE and the block that let a push through was a
deliberately weakened description of the board. The gate could only refuse and the connector
could not supply, so on exactly the boards the feature was designed for nothing could be
created. A template keyed by work item type NAME — the same vocabulary `types.{bug,task,pbi}`
resolve to — is merged into the payload **before** the conformance check, so the board states
what it requires, the manifest states what this project supplies, and the gate grades the
result.

**A collision is refused at validation, not warned about at push.** A template may not name a
field the connector itself maps: winning over one would make `commands/sync.md`'s mapping table
a lie, and losing to one would make the config a lie. A config that cannot do what it says is
better caught when it is written than when it is pushed, and there is no case in which the
setting could quietly start working later. `Microsoft.VSTS.Scheduling.RemainingWork` is the one
deliberate carve-out: the connector writes it at DONE via `onComplete`, never at create, and a
board that requires it at create is the case this module exists for — so it is a warning about
a *second moment*, not a refusal.

**A read-only field is refused rather than attempted, because attempting it can look like it
worked.** Measured 2026-08-24 against the lab board: `--fields System.BoardColumn=…` refuses
out loud (`TF401326`), while `--fields System.Parent=<id>` creates the item, reports success,
and leaves no parent and no relation. "Attempt it and report what ADO said" would report a
create that worked. The same session established that ADO resolves a field's DISPLAY name as
readily as its reference name, which is why both tables here carry both spellings and compare
whole strings — a last-segment rule would refuse a legitimate `Custom.Severity`.

**Values are literals and there is no substitution language.** The fields carrying manifest
data are exactly the ones a template may not name, so a placeholder could only write manifest
data into a field the connector does not map — a change to the mapping table, not something a
config key invents. It would also force every literal to grow a brace escape and every value to
become a string, when an estimate has to stay a number. A value that *looks* like a placeholder
is warned about, because writing those characters onto a board is visible garbage.

### `plugins/audit/scripts/manifest/_ado_parent.py`
Where **one** audit item hangs on somebody else's board, and whether that place can be true
(layer 1). `meta.ado.parentWorkItem` is a single integer for the whole manifest, so every phase
an audit creates was forced under one Feature — the plugin overriding a product owner's decision
about where work belongs. A phase (and a task, when `phaseWorkItems` is false) may now declare its
own `adoParent`, and that key becomes the fallback it always described itself as. Nothing is
deprecated and nothing warns about it: "all of this audit hangs under Feature X" is a real intent,
and a warning on a key that is still the right answer teaches people to skip warnings.

**Three states, and the third is the whole point.** Absent falls through to the fallback —
byte-identical to the behaviour before the key existed, which is what `ap20` pins. An object names
a work item and carries the basis beside the id (`type`, `title`, `source`, `observedAt`). An
explicit `null` hangs under nothing *even when the fallback is set*, which is what makes
uncategorised a **declared** outcome rather than an accident. The same shape `meta.ado.tag` and
every `stateMap` value already read.

**Why layer 1, and why everything arrives as an argument.** `_manifest_crossrefs` and
`_manifest_ado` are both layer 2, so neither can import the other while both need the same answer —
as do `resolve-ado-parent.py` at layer 7 and the panel after it. A second expression of "which
parent" would *be* a second parent. It is also why the module owns its own unknown-key loop:
`_manifest_vocab` is a layer-mate, and `ap9` pins the two loops to one answer rather than a comment
claiming they agree.

**Two surfaces, and they are allowed to disagree.** `hierarchy_violations()` returns `refusals`
(every link the connector must not create) alongside `findings`/`warnings` (how a *manifest* is
graded), and the two are computed in one place so no call site re-derives a severity. A loop an
authored `adoParent` puts there is a finding; a loop reachable through `meta.ado.parentWorkItem`
alone is a warning and the manifest still validates — that key predates the feature, and
`COMPATIBILITY.md` promises a file which validates keeps validating for the whole major line.
The push refuses both, identically, because a `validate-manifest.py` question and a
`resolve-ado-parent.py` question are not the same question. The split reads the whole **loop**
rather than the row being graded, and that is not fussiness: with `phaseWorkItems` on a task
inherits its parent from its phase, so a loop created entirely by the old single `parentWorkItem`
contains a `phase`-sourced task, and a per-row test would fail a manifest its author never touched.

**Three tiers, and only the first is free.** Tier A is structural and offline — an item under
itself, or under something this manifest already hangs under it — so it always has a basis and it
*refuses the create*. It is also the tier that earns its keep: ADO does **not** check an API-created parent
link against the process hierarchy, and a Product Backlog Item whose `System.Parent` is its own
Task exists on a live board right now. Tier B reads `meta.ado.hierarchy`, this project's own
backlog ranks: an inverted pair is refused, an **equal** pair is a note and never a refusal (a Bug
under a PBI is rank 2 under rank 2 wherever `bugsBehavior` is `asRequirements`, and a checker that
refuses a deliberate arrangement gets switched off), and with no cache every link reports `not
verified` while the create proceeds. Tier C is the server's answer, and it degrades **per item**
like the existing invalid-state fallback — never an aborted batch.

**The ranks are asked, never shipped.** The payload that ranks Task under Product Backlog Item
under Feature under Epic also carries `bugsBehavior`, and neither measured project's type list
names a bug at all — that field is the only thing placing it. The same organization runs one
project at `asRequirements` and another at `asTasks`, so a table shipped here would be wrong on the
second board and confidently so.

**The rank has a source and the name had none** (F143). `levels_from_backlog_config()` takes the
bug rung's rank off `bugsBehavior` and its NAME off `bug_type(ado)`, i.e. `meta.ado.types.bug` —
the same derivation `inventory()` stamps a bug row with, so the ladder key and the row graded
against it cannot be two spellings. A literal there filed the rank under a name no work item
carries on a board that renamed the type, and every bug on the most governed kind of board came
back `not verified`. `resolve-ado-parent.py --hierarchy-from` is the door that reaches it: the
function had no caller at all while three documents carried the rule instead (F157).

### `plugins/audit/scripts/manifest/resolve-ado-parent.py`
The door onto `_ado_parent` (layer 7), same shape as `check-ado-item.py` over `_ado_conventions`:
a real command because the caller is orchestrator prose reaching Python through Bash, and a
`python3 -c` one-liner naming a source path is what `guard-secrets-read` refuses.

**A gate, unlike `explain-ado-drift.py`.** Exit 1 means "do not create these parent links", and
that is the right severity here where it is not there: "somebody else moved this card" is a
difference of opinion between two teams, while a loop is a link nothing can build. Exit 2 is
unreadable input, an unknown flag, or a scope naming nothing — **never** 1, because saying "this
does not belong" about something we could not read is the confident wrong answer, and "resolved:
nothing" about an id that does not exist reads exactly like a healthy plan.

**Exit 0 includes "no parent anywhere."** Uncategorised work is an answer and a create, not an
error; `conventions.requireParent` is the board saying otherwise and is graded where the whole
plan can be seen.

**`--hierarchy-from <payload|->` is the same door one question over: it BUILDS the ladder the rest
of the file reads.** `/audit:sync parents` fetches the project's `backlogconfiguration` and used to
assemble `meta.ado.hierarchy` from prose, so the rule for placing the bug rung was written out in
`commands/sync.md`, `reference/tracker-sync.md` and `docs/ado-connector.md` — and moved under all
three when the name stopped being a literal (F157). The mode prints the block whole, `fetchedAt`
included, so a caller copies an answer instead of following a recipe; the manifest stays the first
argument because `meta.ado.types.bug` is where the bug rung's name comes from. Exit 2 covers both
an unreadable payload and one that ranks no backlog level, and it prints nothing on stdout in
either case: an empty ladder cached as evidence reads as a project that ranks nothing, which is
the shape that turns tier B off while looking like a basis. The item flags are **refused** beside
it rather than ignored — `--phase` cannot narrow a question about the project, and a flag that is
silently accepted leaves the caller believing it applied.

**The hierarchy is computed over the whole plan; the verdict is scoped.** A loop is a property of
the graph and not of the item you asked about, so `--phase P3` still finds one that leaves P3 —
and the refusals outside the scope are counted and named rather than dropped, without changing the
exit code. The narrowing happens once, in `scope_result()`: the printed refusals and the exit code
came from two separate walks while this file was being written, which is exactly the shape that
lets a command exit 1 over something it never printed.

### `plugins/audit/scripts/manifest/_ado_tracked.py`
Whether one audit item belongs on the shared board **at all** (layer 1) — the question one step
before `_ado_parent`'s. `/audit:sync status` could not tell **deliberately untracked** from
**drift**: a phase nobody ever intended to put on Azure DevOps reported as `unlinked` on every run,
for ever, so the drift lens grew one permanent false positive per such phase — and a lens carrying
permanent rows stops being read, which costs it the real drift it exists to catch. `phase.ado`
could not carry the intention either, and that is a fact about the field: `ado` is an `adoLink`
that *sync writes*, so declaring an intention there would be authoring into a record.
`phases[].adoTracked` is the authored sibling, exactly as `adoParent` is.

**Absent means tracked**, which is what makes the key shippable: a plan that never sets it resolves
precisely as it did before the key existed, and `at3` is the case that fails if that ever stops
being true. `false` is deliberately off the board; `true` is the same answer said out loud.

**A task inherits under both settings of `phaseWorkItems`, and the two are not one rule wearing two
hats.** With phase work items on the inheritance is *forced* — a task hangs under its phase's work
item and an untracked phase has none. With them off the task would get a work item of its own, so
mechanics decide nothing: the phase is the unit an operator chose to keep off the board, and
honouring that at the phase while pushing its tasks anyway puts the same work on the same board
under another name. The answer is the same, the **basis** is not, and the basis is the half a
reader has to check.

**A bug is not answered, rather than answered `tracked`.** Bugs are owned by no phase, so there is
nothing to inherit, and `bug.ado` is usually written by a *pull* off somebody else's board —
calling that tracked would be the plugin claiming a card it never created. So `tracked` is
**three-valued**: `True`, `False`, and `None` for "no basis to answer", with `is_tracked()` /
`is_untracked()` named so no caller decides for itself what a falsy `None` meant. A truthiness read
files an unanswered item as deliberately untracked, which is the exact collapse the feature undoes.

**Why layer 1, and why the manifest arrives assembled.** `_ado_parent`'s argument exactly: the push
plan, the status lens, the validator's neighbours at layer 2 and `resolve-ado-tracked.py` at layer 7
all need the same answer, and two of those are layer-mates that cannot import each other. Reading
the file here would mean importing `_manifest_io`, a layer-mate, and would push the module to layer
2 where half its consumers could not reach it.

**And it detects the un-assembled sharded index rather than trusting its caller.** In the sharded
layout the file at `manifestPath` is an *index* whose phases are stubs, while `adoTracked` and
`tasks` both live in the shard body — so a caller reaching for `json.load` sees no declaration on
any phase and no task at all, and reports a deliberately internal plan as **tracked, by default**,
on the layout parallel worktrees use. A phase still carrying a `shard` key is therefore not
resolved: it is reported unanswered, naming the shard and the loader, because a stub is a missing
basis and a missing basis is the thing to say. `at31` is that case and `at33` is its second
direction.

### `plugins/audit/scripts/manifest/resolve-ado-tracked.py`
The door onto `_ado_tracked` (layer 7), same shape as `resolve-ado-parent.py` over `_ado_parent`: a
real command because the caller is orchestrator prose reaching Python through Bash, and a
`python3 -c` one-liner naming a source path is what `guard-secrets-read` refuses. It renders a
human block and `--json`, and `--all` is the default because the push plan needs the whole picture
and a command whose default answers about nothing is one people forget to scope.

**Not a gate, and the missing exit code is the load-bearing one.** `resolve-ado-parent.py` exits 1
because a hierarchy violation is a link nothing can build. "This phase is not on the board" is a
normal state somebody authored on purpose, so **exit 1 is not in this command's vocabulary at
all** — `rt60` asserts that over every run the suite makes, collected as they happen rather than
over the fixtures somebody remembered to list. Exit 0 includes *"nothing is tracked"*, and that
answer gets its own closing sentence rather than the ordinary OK line: a success line that reads
the same whether every phase was planned or none is the shape that gets believed on the wrong day.
Exit 2 is unreadable input, an unknown flag, or a scope naming nothing — "tracked: nothing" about
an id that does not exist reads exactly like a plan somebody keeps deliberately internal, which is
the one confusion this feature exists to end.

**Every count prints at zero**, the bug line included, because a count that appears only when it is
non-zero cannot be told from a count nobody took. A scoped run also prints what it did *not* ask
about, and carries both tallies in `--json` (`counts` for the scope, `manifestCounts` for the
file): a consumer given only the first cannot tell a manifest that tracks nothing from a scope that
happens to contain nothing tracked.

**It loads through `_manifest_io`, which is the half the rules cannot do from the floor.** `rt40`
pins that end to end on a real index-plus-shard fixture, and `rt41` asserts off the *file* that the
index carries neither the declaration nor a task — two computations, so the pair is a result rather
than a value compared with itself.

### `plugins/audit/scripts/manifest/_manifest_ado.py`
`meta.ado` — the Azure DevOps connector's config, checked offline (layer 2). **ONE front
door**: `validate()` calls `check_ado_meta` for the manifest and the panel's `write_ado`
(PUT `/api/ado`) calls it for a candidate save, so the CLI and the panel cannot disagree
about what a valid connector config is. Wrong **types** are findings (a config that would be
misread); unknown **keys** are did-you-mean warnings — `statemap` configuring nothing is
exactly the silence worth naming, and a typo'd `stateMap` status key silently never fires.
`identityMap` is advisory in use and structural in shape; a duplicate target is only a
warning, because one person can legitimately hold two ledger identities.

### `plugins/audit/scripts/manifest/_manifest_typos.py`
The **did-you-mean** detectors (layer 2): a model id or a skill name used exactly **once**
while a near-miss neighbour is used often. Warnings only, `findings` always empty — a near
miss is a guess about intent, not a structural defect. A spelling used twice is an
established choice and is never flagged, which is what keeps this off two models a project
picked on purpose. The window is one slip for a model id and two only for skill names of 6+
characters, because on short names two edits turn one real name into another. Deliberately
**intra-manifest**: whether a model exists or a skill is installed is the panel's question,
since it has the rate table and the discovery inventory in hand and this validator has
neither. `_check_skills` is gated on `_skills_in_use`, so a manifest that never touches the
feature gets zero new lines.

### `plugins/audit/scripts/manifest/_manifest_crossrefs.py`
Every question about how one part of the manifest **refers** to another (layer 2): unique
ids across the one phase/task/bug namespace, `blockedBy`/`dependsOn` resolution, dependency
cycles, `fileIndex` integrity in **both** directions, the reciprocal `bug ↔ task` link, and
parked `proposals[]` (reserved ids, staged refs, the `materializedAs`/status pair). Each
takes the index `_manifest_phases` produced plus, for three of them, the manifest, and
returns its own `(findings, warnings)` — no accumulator shared, no order depended on, so a
case can call any of them with a hand-built index and no manifest anywhere near it.

### `plugins/audit/scripts/manifest/_warning_groups.py`
The **shape** a repeated warning prints in (layer 2), and the reason it is not inside the rule
that produced it. On a real plan the unresolved-skills advisory printed one line per task —
every mutating command, every run — and what it cost was not the verbosity but the signal
those lines buried: a priority warning naming a phase that waits on work nobody has done sat
inside the block, unread. `validate()` has no notion of a repeated finding at all, so every
per-item rule has this latent; repairing it where the lines are rendered covers the next one.

Two warnings are **one finding** when the text after their locator is equal byte for byte —
which needed no change to what a warning carries, because a warning is already
`"<kind> <ident>: <body>"` wherever it names an item and `locator()` round-trips. Equality is
the conservative reading: a differing parenthetical basis keeps its own line, since the basis
is half of what the reader acts on. What the string could *not* decide is which phase a task
belongs to — `P0.1` implies `P0` only by a convention the validator merely warns about — so
the owner is read from `_manifest_io.iter_tasks`, and a caller with no manifest degrades to
naming items rather than to guessing.

A group of one renders its original line verbatim. Above `NAMED_MAX` the line names the
owning phases and the command that names every id; findings are deliberately **not** collapsed
(they stop the command and are read one at a time, and their count already has a line that
prints it). Groups render in first-occurrence order, so two runs over one file print the same
bytes.

### `plugins/audit/scripts/manifest/validate-manifest.py`
The command over those rules, and nothing else: read the file, print `WARNING:`/`FINDING:`
lines, choose the exit code. Exit 0 clean (warnings allowed) / 1 findings / 2
usage-or-unreadable. It re-exports exactly one name (`validate`), and a case fails if a
second one creeps back. Warnings go through `_warning_groups` on the way out, so a rule that
fires once per task prints one line naming the count and the phases; `--verbose` prints them
one per item and is the flag every elided line names. Findings are printed as they come — see
that module for why they are not grouped. The `OK:` tail keeps counting WARNINGS and not
lines, because the two are meant to differ and the collapsed line says its own size aloud.

### `plugins/audit/scripts/status/_status_facts.py`
What the manifest SAYS, as a machine-readable answer (layer 2) — the half of status that
nobody prints: `rollup`, `ready_tasks`, `unmet_refs`, `_status_index`, the submodule
preflight (`parse_gitmodules`, `submodule_conflicts`), the high-severity vocabulary, the
test-evidence vocabulary (`NO_SIGN_OFF_EVIDENCE`, `evidence_status`, `evidence_rows`,
`test_evidence_summary` — which words cannot sign work off, spelled as a positive set so a
member the enum gains later is reported rather than folded into `failed`), and
the gate (`CONDITIONS`, `DEFAULT_GATE`, `evaluate_gate`, `budget_breaches`). Pure dict→dict
throughout: nothing here opens a file or runs a process, which is what lets three modules
share it — `_panel_state` (rollup), `audit-doctor` (submodules) and `render-report`
(the gate verdict) each used to load `audit-status.py` for it, three of the seventeen
`KNOWN_LAYER_DEBT` edges. `usage_summary` and `discovery_block` do read the world, so they
stayed with the command.

### `plugins/audit/scripts/status/audit-status.py` (v0.5.0)
Headless rollup + CI gate, stdlib-only; the facts come from `_status_facts`, the manifest
rules from `_manifest_rules`, both by plain import. `--json` prints the machine-readable
summary (phases done/total, tasks/bugs by
status, ready-task list mirroring /audit's readiness rule); `--gate` exits 1 on tripped
conditions — default `invalid,open-high-bugs,blocked-tasks`, tunable with `--fail-on`
(also `open-bugs`, `in-progress` for release freezes, and `failing-tests` /
`no-test-evidence` over the manifest's `testEvidence` pointers — both opt-in, because a
plan that has never recorded a run must not start failing builds on upgrade, and both
read phases as well as tasks). The human render carries the same words in a `tests`
column, which — like the report's optional columns — is drawn only when a task in view
has recorded a run, so an unchanged plan renders exactly as it did before.
`--submodules <.gitmodules> [--git-root
<prefix>]` (v0.6.2) is the submodule preflight guard — exit 1 when any `task.files` entry lives
inside a git submodule (which the parent repo cannot stage/commit). Exit 0/1/2. `--selftest`
.

### `plugins/audit/scripts/status/audit-doctor.py`
`/audit:doctor`'s "is this working?" diagnostics — every check reuses an existing
implementation (`_config_rules.validate_config`, `_manifest_rules.validate`,
`_status_facts.submodule_conflicts`, `usage_ledger.find_ledger_dir`) rather than
reimplementing it, so a rule never means one thing here and another at the gate. It is
read-only by construction: it never writes, never takes a lock, and for `buildCommands`
resolves whether the named executable exists rather than running it. Output classes match the
rest of the plugin (OK/WARNING/FINDING); exit 0 healthy, 1 findings, 2 usage error.

It was 1,456 lines and is a fraction of that - `wc -l` on it says how much - because the
checks shared one file for the single reason that `diagnose()` calls every one of them. What
is left here is the thing that could not go into a piece: the ORDER (`check_config` produces
the `cfg`/`cfg_mod` pair, `check_git` the git root, `check_manifest` the manifest — ten of
the checks after them take those as arguments), plus `render()` and `main()`, because a
report's order and its rendering are one subject. Every name the six modules hold is
re-exported here as a module-level alias, so the suite and the command both keep spelling
one import.

### `plugins/audit/scripts/status/_doctor_report.py`
The piece all six check modules sit on, and the only one with no check in it: the `Report`
collector (rows of level/check/detail/fix, plus `counts()` and `exit_code()`), the `_load`
wrapper every check reaches a sibling or a hook through, and the two constants two modules
each read (`LAUNCHER_INTERPRETERS`, `RECENT_DAYS`). Layer 2 — it imports `_loader` and
nothing else — which is what lets consumers as high as layer 5 share it. `_load` fixes
`cache=False` on purpose: `tests/test_audit_doctor.py` re-`diagnose()`s ONE fixture it mutates
between calls, in one process, and a cached module would be indistinguishable from a
regression. Sharing the wrapper across files is also why `_deps._borrowed_wrapper_names`
exists: the wrapper is defined here and the `.py` literals are spelled in the six callers, so
without it a dozen real runtime edges would be invisible to the layer lint.

### `plugins/audit/scripts/status/_doctor_setup.py`
The checks everything else stands on: which interpreter `py-launch.sh` will resolve, the
git root the orchestrator will run git against, whether the config parses and validates and
which plan-gate tier it produces, whether the manifest assembles and validates, whether a
sharded layout's shards are intact (the assertion that moved out of `ci.yml` so CI and this
command call one implementation), and whether any `task.files` entry lives inside a submodule
the parent repo cannot stage. Layer 4, set by `_manifest_rules` at layer 3.

**`check_sandbox` (P0-S) is the same question one layer down**, which is why it sits beside
`check_interpreter` rather than in `_doctor_hygiene`: that one asks whether the guards can run
at all, this asks whether the layer they LEAN ON is there. The plugin's secret guards match
tool-call text and never observe I/O, so what actually contains a read is the harness sandbox
plus `permissions.deny` — neither of them this plugin's, and neither ever checked. Two rows:
`sandbox` and `secret rules`.

**Its whole design is about what it may not claim.** Claude Code exposes no environment
variable carrying sandbox state, and this command is read-only by construction, so it may not
probe by attempting a write — settings FILES are the entire basis, and two merge layers
(managed/MDM policy, a `--settings` flag) outrank every file it can read. So the answer is
THREE-VALUED: declared true, declared false, and **not established**, which is reported as
exactly that and never as "off". Grading follows the doctor's own taxonomy rather than how
alarming the subject sounds — an explicitly disabled sandbox is broken now (FINDING), an
undeclared one will bite later (WARNING), and a missing dotenv deny rule is a WARNING beside a
working sandbox but a FINDING beside an explicitly disabled one, because at that point the only
thing between a secret and the transcript is a regex over tool-call text. When the sandbox is
merely UNATTESTED the missing rule is a WARNING as well, and that is the same principle rather
than a discount: a finding there would assert the layer is absent, which is exactly what this
check cannot establish, and `/audit:doctor` exits non-zero on findings — so grading it that way
failed the doctor for every repo that had configured neither layer, on upgrade, in CI. The
warning says WHICH of the two it is. Scalars take the
highest-precedence file that defines them; rule LISTS merge across scopes, the way Claude Code
merges them. An unparseable settings file is reported, not skipped — the harness is not
applying its rules either, and "no rule found" would name the wrong cause.

### `plugins/audit/scripts/status/_doctor_policy.py`
The three checks that compare a declaration against the world it claims to describe:
`meta.areas` roots against the tree and phase tags against the registry (v0.28), the
capability policy against the plan it governs and against this machine's inventory (v0.30,
dead patterns v0.38), and `meta.buildCommands` runners against PATH. Every row is a WARNING
at most — a missing directory or an uninstalled runner is a gap in this checkout or this
machine, never proof the repo is broken, which is the lesson CI's manifest job taught by
failing over a correct observation. `_leading_executable` resolves what a command would
actually run (`cd x &&`, `env`, `VAR=v` prefixes) and returns None rather than guessing at
shell control flow. Layer 5, set by the `_panel_discovery` load `check_policy` makes.

### `plugins/audit/scripts/status/_doctor_ado.py`
The ADO connector's operational half (connector v2), offline by construction — a doctor that
phoned ADO would be a doctor that needs credentials. The SHAPE of `meta.ado` is
`_manifest_ado.check_ado_meta`'s job and arrives through `check_manifest`; what is here is
what a shape-checker cannot see: whether `az` and its `azure-devops` extension are installed,
which switches are in effect, that the shipped `stateMap` defaults name Agile states a Scrum
project does not have, that `onComplete.remainingWork` degrades to state-only under both
stock processes, and what the manifest's links actually prove. Layer 3.

### `plugins/audit/scripts/status/_doctor_trail.py`
Has anything run here, and does what it wrote still hold? Hook state files are the only local
evidence a guard ever fired, ledger files the only local evidence metering ever wrote, and
the journal chain the only local evidence a completion was recorded. Each says WHICH of
"never started" and "stopped" it is looking at — a disabled journal with rows on disk is a
warning, a disabled journal with none is an ok line. `check_journal` delegates to the
journal's own `verify` rather than re-deriving the verdict, and grades a broken chain a
FINDING while a torn tail or out-of-band drift stays a warning.
`_journal_never_committed` rides `audit-journal`'s porcelain seam for the 7-day
uncommitted-file warning, keyed by journal-relative path so a live and an archived month
cannot read as one another. Layer 4, set by the `usage_ledger` load.

### `plugins/audit/scripts/status/_doctor_completions.py`
The one check that CORRELATES two records rather than inspecting one: the journal's
hook-emitted `task.complete` rows against the manifest's done tasks, the commit SHAs those
tasks name against what git has, and the usage ledger's coverage of the same ids. A done task
inside the record era with no record is positive evidence the manifest was edited outside the
pipeline — a FINDING, as is a SHA git has never heard of; everything the check merely could
not look up is a WARNING. The era is the WATERMARK with no config knob: the first
`task.complete` row's `ts`. `--deep` adds the journal-in-commit cross-check. Layer 4.

### `plugins/audit/scripts/status/_doctor_hygiene.py`
The two questions about the working copy itself: what is HELD, and what is LEAKING.
`check_locks` delegates to `_locks` rather than re-deriving the verdict — this check once
called anything older than 60 minutes stale, which told the human a healthy 90-minute phase
run had crashed. `check_local_artifacts` (v0.35) catches what the self-ignoring writers
cannot reach: the ledger, stateDir, logsDir or panel pidfile committed BEFORE the markers
existed. The journal is deliberately not in that list — it is the opposite kind of artifact
and must stay tracked, which is the reverse warning `_doctor_trail` carries. Layer 3.

### `plugins/audit/scripts/status/_gate_feed.py`
The plan-gate events feed (`<logsDir>/plan-gate-events.jsonl`) as something that can be
CLEANED, not only appended to. `hooks/_config.append_gate_event` writes it and the panel's
Plan gate card reads the tail; nothing in between could remove a row, so a user who wanted
rows naming a scratch directory outside their repository gone had to hand-write Python
against a file this plugin both produces and displays.

`classify()` splits raw lines into what stays and what goes, in named classes — a `file`
resolving outside the repository (`hooks/_config.within_root`, the same containment question
require-plan and remind-tdd ask), a line that is not a JSON object, and, **only when a caller
names a threshold**, a row past that age. There is no default age and that is the decision:
the feed already self-trims by size, and "old" is not the same claim as "does not belong".
A row is scored in the first class it falls into, so the class counts add up to the removed
total, and every class is reported including the ones at zero.

**One thing is deliberately NOT a class**: a row an older release wrote, whose `file` may hold
a whole shell command and whose `reason` may hold an absolute path. Both writers are fixed and
neither fix reaches what is already on disk; nothing in a row records which release wrote it,
so classing them would mean guessing at a shape and *removing* on the guess — and a
repo-relative path containing a space reads exactly like a program with an argument. What the
rule returns instead is `oldestKeptDays`, how far back the feed still reaches once the prune
has run: `None` when no kept row carries a readable stamp, never zero, because a feed starting
today and no row being willing to say are different answers. Age is the only lever that reaches
those rows, and that number is what aims it.

`feed_path()` is the blast radius, and it is CONSTRUCTED rather than checked after the fact:
the writer's own `logs_dir()` + `GATE_EVENTS_FILE`, so no argument can widen it. Its one
refusal is a feed that is a symlink out of its own directory — the gate appends *through*
the link while `atomic_write_text` ends in `os.replace`, so a prune would swap the link for
a file and silently redirect the feed. That test is an EQUALITY between resolved directories
rather than `within_root`, because the two questions fail in opposite directions: a gate that
cannot resolve a path must answer *inside*, and a writer that cannot must not proceed.

`prune()` is the whole action, and both doors run it — `audit-logs.py` and the panel's
`POST /api/gate-events/prune`. It writes nothing when nothing was removed, so a prune that
changes nothing leaves the mtime alone. Layer 2 (it reaches `_loader` and `_usage_core`, both
layer 1). `--selftest`.

### `plugins/audit/scripts/status/audit-logs.py`
`/audit:logs` — argument parsing, the render and the exit code over `_gate_feed`. It is its
own entry point rather than `/audit:doctor --prune-events`, which is what was asked for, and
the argument is in the file's own docstring: the doctor is read-only by construction and
three surfaces promise it, but the decisive part is the shape — `--prune-events` would have
to skip `diagnose()` entirely, and a flag that skips the whole body of a command is a
different command wearing that command's name. The doctor's exit code is a health verdict
with nowhere to put a prune's outcome.

The name is the boundary: everything reachable lives under `logsDir`, and the journal is
deliberately out of reach because it is the tamper-evident trail. **Both counts print at
every value including zero**, `state` separates a feed nobody has written from an empty one,
and removed rows are counted by class and never echoed — printing an out-of-repository path
to explain that it was removed writes it back into the transcript the prune was clearing.
It also renders the limit the rule cannot decide — an `oldest` line plus the standing note
about rows an older release wrote — and only where there is history for it to be about, on a
feed that exists with rows left in it. "Nothing to remove" is otherwise a true statement about
the rule and a misleading one about the file. The verb is mandatory: a bare invocation must
not prune. Exit 0 the prune ran, 1 it could not, 2 a usage error. Layer 7. `--selftest`.

### `plugins/audit/scripts/governance/_locks.py`
The lock library (layer 1): where a lock lives (`lock_dir`), what it may be called
(`valid_name`), whether its holder is alive (`pid_alive`, `judge`), what is held
(`read_lock`, `collect`), and taking or giving one back (`acquire`, `release`). Liveness,
not age, decides a stale lock, and every verdict carries the BASIS sentence that makes it
checkable. It is at the bottom of the graph because four callers ask about a lock and only
one of them is a command: `_panel_state`, `audit-doctor` and `audit-usage` each loaded
`audit-lock.py` through `_loader` (three of the seventeen `KNOWN_LAYER_DEBT` edges), and
`hooks/_config.py` resolves it by path on every tool call — so the module it reaches for
should be small. `audit-task.py`'s dependency was the one nothing could see: it took the
index lock by building an argv and calling `main()` through `_panel_write._lockmod()`, so
`_deps` attributed the edge to the panel. It is an ordinary import now.

### `plugins/audit/scripts/governance/audit-lock.py`
The CLI over `_locks`: `acquire <name>`, `release <name>`, `status`, over the two tiers the
orchestrator uses (`index`, `phase-<id>`), turning the library's answers into exit codes —
a live holder is refused (exit 3); one that is not alive can be seized with `--takeover`
(exit 4), because the old "older than 60 minutes = crashed" rule was wrong in both
directions. `--session`/`--pid` override the identity written into the lock for testing.

### `plugins/audit/scripts/governance/_invariants.py`
The post-hoc reader of `reference/orchestrator.md` (layer 4). Both READMEs split the
plugin's rules into what a hook ENFORCES and what the model FOLLOWS, and the second table's
last column names, per row, what evidence would catch a breach — `post-hoc` where git, the
shard, the journal or the ledger already holds it. This module reads that evidence, check by
check — `CHECK_NAMES` is the list and `verify-invariants.py --all` prints it: a task commit
staged only its own `files`, its phase's manifest file and the two records beside it
(`git show --name-only`); an **audit-state** commit staged those records and *not* the task's
`files`, found through the journal's `audit.state.committed` rows because nothing in the
manifest names such a commit; no push, no forced update and no stash touched the phase
branch (the remote-tracking refs, the branch's own reflog compared pairwise for ancestry,
and `refs/stash`); every manifest state the phase COMMITTED still validates (each commit's
index and shards reassembled through `git show` and run back through `_manifest_rules`); a
`risk: "high"` task ran on neither a declared nor a metered `haiku`; and `phase.baseRef` is
an ancestor of the parent `_branch.parent_branch` resolves.

`audit-state-scope` sits next to `commit-scope` rather than at the end because it asks that
check's question about a different commit, and the two allow-lists differ in exactly one
entry — the task's `files`, which one permits and the other forbids. Its `no-basis` case is
its own: with `journal.enabled` false there is nowhere such a commit could announce itself,
which is *not* evidence that none was made.

The verdict vocabulary is the design. `clean` / `breach` / `partial` / `no-basis` /
`not-applicable`, with `examined` beside each — so a check that looked at nothing prints the
loudest word rather than the calmest, and a finished phase whose branch was deleted at
sign-off answers `no-basis` about its reflog instead of `clean`. What it cannot see is in
the module docstring rather than left for a reader to discover: a dropped stash, a push from
another clone, and the manifest states written between two commits, which it counts from the
journal's `stateHash` rows instead of passing over.

### `plugins/audit/scripts/governance/_evidence_io.py`
Where a test-execution record lives, and what it is allowed to say.

`run-test-gate.py` already answers the two questions an exit code cannot — did the gate change
the tree, and did anything actually run — and then throws every answer away: it performs no disk
I/O at all. This module is the memory it never had.

**Not the journal, and the reason is the journal's own rule.** `_journal_io.DETAILS_KEYS` is an
allow-list whose three stated tests are that a key names a FIELD OF THE PLAN that moved, that it
is bounded, and that it exposes nothing new. An exit code, a duration and a check count fail the
first outright — they are things the plugin *observed about the machine* — and `MAX_DETAILS_BYTES`
would clip a multi-step run besides. So runs live here and the journal ANCHORS them by `runId`,
which is a plan field and passes all three.

**Not `<ledgerDir>` either.** That is local scratch which writes its own `.gitignore`; this is
evidence for an audit somebody hands to a client, so it sits beside the manifest and is committed,
exactly like the journal. The two differ in what they are for, not in where they belong.

Layout is `<evidence dir>/<YYYY-MM>.<writerId>.jsonl`, default `<manifest dir>/evidence`, with
`evidence.dir` as the override. One file per writer per month — the journal's argument and not a
decoration: two sessions in two git worktrees append at the same time, and a single shared file
would conflict on every merge, the one thing the sharded layout exists to avoid.

`evidence_dir()` derives from `manifestPath` rather than hardcoding, so a repo that moved its plan
does not end up with the record of it somewhere else; the resolution is deliberately the same
shape as `journal_dir()`, because two expressions of "where does this manifest keep its committed
record" would separate the trail from the evidence the first time a repo set an unusual path.
`in_evidence()` is the membership question a guard asks, and its prefix test carries the separator
— a boundary its cases assert from the outside, since a prefix test without it admits every
sibling whose name merely starts the same way.

**A row is assembled from named fields, never copied.** `row_for()` reads the keys it knows out of
the runner's result and nothing else, which is what makes *no runner output is ever written here* a
property of the writer rather than a habit each call site has to remember — the gate runner holds
full merged stdout in memory while it counts checks and scrapes paths, and none of it has a route
into this file. A **command the manifest publishes** is stored verbatim, because the plan already
carries it in plain text and storing it exposes nothing new; anything else falls back to
`command_facts()` — digest, byte length, program name. Paths go through the journal's
`repo_relative_or_token`, since this file is committed and an absolute path in it names somebody's
machine in a repository that goes to clients.

**Cuts announce themselves.** A run wider than `MAX_STEPS` or `MAX_PATHS` is trimmed and the row
carries the count of what went — and a row that *fit* carries no count at all, because a number
appearing only when non-zero cannot be told from one nobody computed. Three-valued fields keep
their shape end to end: an unknown tree stays `None` rather than flattening to the empty list a
truthy reader would call clean, and a step's `ran` keeps its `None` rather than vanishing into
"absent", which a reader could mistake for zero.

**`read_rows()` counts what it lost.** A torn line is skipped *and* counted, which is where this
departs from `usage_ledger.read_ledger`'s silent `continue`: that is right for telemetry and wrong
for evidence. It reports the file count too, because "no rows" and "no files" are different answers
and a bare list could not tell them apart.

**The manifest pointer is a cache, and the write that updates it is the one allowed to fail.**
`write_pointer()` puts three keys — `runId`, `status`, `at` — on the task or the phase, **in the
shard and never the index**: a phase run that touched the index is what makes two parallel phases
conflict on merge. Every `written: False` is a designed outcome carrying a sentence, not an error
path. `pointer_lock_state()` answers `free` / `ours` / `held` / `stale` / `unlockable`, and **`ours`
exists because `_locks.acquire` is not re-entrant** — a gate recorded from inside its own phase run
meets the lock that run already holds, so the holder's session is *compared* rather than the lock
re-taken. A stale lock is not taken over here; that is a decision a human makes with
`audit-lock --takeover`. A refused pointer leaves the ledger row standing and names `--reconcile`,
which is the only reachable partial state and the harmless one.

**`reconcile()` is that repair**, and it is why the refusal is affordable: it re-derives every
pointer from the ledger, newest run per subject **by `ts` and never by file position** (rows land in
one file per writer per month, so two worktrees concatenate in no meaningful order). Running it
over an already-correct plan moves nothing and says so — a repair that rewrote a correct pointer
would put a fresh journal row on every invocation, a trail of transitions that never happened. A
reconcile that could not finish reports the subjects it left behind rather than returning a smaller
number.

**The plan-movement row is the second of C4's two events.** `task.testEvidence` /
`phase.testEvidence` is written **only after the pointer lands**, naming both ends of the move; a
refused write returns before reaching it, so the chain can never assert a transition that did not
happen. That is why it is a separate action from the anchor below, whose subject is the evidence
file and which was true the moment it was written.

**`record()` writes the ledger row first and anchors it second**, so the only reachable partial
state is the harmless one — a run that happened with nothing yet pointing at it. The reverse would
put a claim into a hash chain about a row that does not exist. The anchor's subject is the evidence
file and it says only that a run was *recorded*, which is true the moment it is written; the row
that says the **plan** moved belongs to whoever moves it and must not be written before that
happens. The ledger half is deliberately **not** fail-soft: a run whose evidence could not be
stored must not be reported as recorded.

**`evidence-committed` is `audit-state-scope`'s other half.** That one grades what a commit
*staged*; this grades what the committed plan *points at*. A `testEvidence` block is a cache at a
row in the ledger, so a pointer that survives a clone while its row does not is a plan referring to
evidence that did not travel with it — and the working tree is exactly where that looks fine, which
is why both the listing and the reading come from `HEAD` rather than from disk. The claim is
narrower than the invariant and the difference is stated: it asks about HEAD, not about every state
the phase ever committed, because a pointer briefly unsupported and since repaired is not a fault a
reader can act on. An evidence directory outside the git root is **not-applicable, never a breach** —
it cannot be committed there at all, so the plan is not at fault for naming rows git was never going
to hold. A torn committed row is a **gap**: it says a row could not be read, never that a pointer is
unsupported.

### `plugins/audit/scripts/governance/verify-invariants.py`
The CLI over it: `verify-invariants.py <manifest> <phaseId>`, or `--all` for every phase that
has started (a branch, a `baseRef` or a recorded commit). `--json` for the whole answer,
`--project` for the directory holding `.claude/` and the journal. Exit 0 answered, 1 at least
one breach, 2 usage error or unreadable manifest — and a missing basis is deliberately exit 0
with the word in the output, because sign-off deletes the phase branch and a gate that fired
on absent evidence would fire on every finished phase. Wired into Phase sign-off and into
`/audit:status --gate --fail-on invariant-breach`.

### `plugins/audit/scripts/governance/commit-audit-state.py`
`commit-audit-state.py <manifest> <phaseId>` — **commit any uncommitted audit state, or say
there is none.** Idempotent and safe to call unconditionally; `--project` names the directory
holding `.claude/` and the records, `--subject` supplies the commit subject after the
conventional prefix, `--json` prints the whole answer. Exit 0 it ran (committed, or nothing was
uncommitted), 1 it could not, 2 usage error.

**The gap it closes.** Evidence is written beside the manifest and is meant to be committed, but
the orchestrator commits on success and only on success: a red gate leaves `in_progress` and
step 4 says *do not commit*, an infrastructure failure STOPs without committing, and the
sign-off commit waits for green. The gap is **narrower than "every failure"** — a task commit
stages the evidence directory, so a run that fails at attempt one and succeeds at attempt two is
already durable, its failure included. What is not durable is a run whose task or phase never
subsequently commits at all.

**What it stages, and what it can never stage.** The phase's manifest file (the shard when
sharded, else the single manifest), the journal directory, the evidence directory. The task's
`files` are not on that list and cannot be put on it — a failed task's code stays out of git,
which is the entire point of a separate verb. Paths are staged **explicitly** (`git add --
<path>…`, never `git add -A`) and the index is read back with `git diff --cached --name-only`
and compared against the same allow-list **before** the commit. The index is read **before**
staging too, so work somebody else had already staged is refused while the index is still
exactly as it was found rather than unpicked afterwards. A directory outside `<gitRoot>` is
degraded past and named, the sentence step 4c already writes for the journal.

**Never an empty commit**, and a distinct conventional type. Nothing staged means no commit and
a line saying so — a stream of empty commits is how a record stops being read. The type is the
fixed literal `audit-state`, which is the only spelling a task commit cannot collide with
(`meta.commit.type` may be anything), so `git log --grep` separates the two for ever.

**It anchors itself in the trail.** After committing it appends an `audit.state.committed`
journal row whose `details` carry `commit` and `phaseId` — the only handle anything has on such
a commit, since it is not a `task.commit` and the manifest does not name it. That is what
`_invariants.audit_state_scope()` reads to find these commits and grade them; the row's target
is the **evidence directory** and deliberately not the phase's manifest file, because
`_recorded_states()` reads every row naming that file as a *write* to it and a commit is not an
edit. The append is fail-soft (`_journal_io.append`'s contract) and the failure is printed: a
commit that happened must not be reported as not having happened.

### `plugins/audit/scripts/governance/run-test-gate.py` (v1.4.2)
Runs a phase's `testGate` and answers the two questions an exit code cannot (F193).

**Did the gate change the tree?** `git status --porcelain` before and after. A gate is a
MEASUREMENT; one with side effects has answered a different question than the one asked, and
a commit built on it carries work no task owns and no review saw. Any difference prints
`GATE MUTATED THE TREE: <files>` and refuses **regardless of the gate's own exit code**.
Measured live: a docs task's `pre-commit run --all-files` rewrote five backend source files —
`isort` and `black` are fix-in-place and reported `Passed` *because* they had.

**Did anything actually run?** Runners that report their own step count are read and the count
printed; zero is `NO CHECK RAN`, which is not the word green. The same live run, narrowed to
the task's two markdown files, SKIPPED every hook on a Python-only config: exit 0, nothing
verified, task done. One design, both failure modes, and the exit code separated neither from
a verdict. A runner that does not report a count yields `None`, printed as not-knowable —
guessing zero would refuse a passing gate and guessing one would bless a skipped one.

Exit 0 passed / 1 a command failed, or the tree moved, or nothing ran / 2 could not be asked.
An **empty** gate exits 0 and is reported as itself, never as green: `audit-task.py:_phase_gate`
documents it as a designed state, and printing green would claim a measurement nobody made.
Git that cannot describe the tree is `UNKNOWN` and says so rather than reading as clean.

A script and not an instruction in `reference/orchestrator.md` for the reason
`journal-writes.py` gives against a prompt: a rule that depends on the model remembering holds
until a session forgets, a harness runs a different orchestrator, or somebody adds a gate by
hand next year. It does NOT narrow the gate to the task's files — that changes what a per-task
gate means for every manifest already written, so the refusal names the option and a human
decides.

**Recording is opt-in and lands strictly after the verdict.** `--record` writes the evidence row,
the journal anchor and the manifest pointer — all three inside the repository this run has just
described with `git status --porcelain`, which is why every one of them happens in `main()` after
`run_gate()` has returned. A write above that line would appear in the very comparison it is being
judged by, and the runner would accuse itself of the rewrite it exists to catch; a case drives the
whole path and goes red the moment anything moves above the snapshot. `--reconcile` runs the ledger
against the plan and nothing else — no gate, no subprocess — so it is safe to hand a human who has
just been told their pointer did not land.

**Whose gate ran is answered, not assumed.** `gate_of` takes an optional task id and returns the
resolved commands *plus the scope they came from*. A task declaring `tests.gate` is run through its
own commands; one declaring none falls back to the phase's and **says so**, because "this task's
gate passed" and "the phase's gate passed while pointed at this task's files" are different claims
for a record to make. Absent and empty are one answer; an unknown task id is an error rather than a
quiet fallback, the distinction `owned_files` already draws.

**What did not finish is separated from what failed.** A timeout and a failure to *start* used to
be one answer — both were swallowed into `except Exception` and reported as exit 127, so "the suite
hung" and "the binary is missing" arrived identical. They are different repairs, so they are
different words, and neither is read out of an exit code: 124 and 127 are codes a real command may
return on its own, so the category comes from what the wrapper observed and travels beside the code.
A missing binary under `shell=True` is therefore still a *failure* — the shell started fine — and
that limit is pinned by a case rather than papered over.

**The process GROUP is torn down, not just the child.** `subprocess.run(timeout=)` kills the direct
child, and under `shell=True` that child is the shell: `npx` → `node` → its workers outlive it, keep
running and keep **writing** — into the very tree this script is about to describe. So a step is
spawned into its own session (or process group on Windows) and stopped with `killpg`, a grace
period, then `SIGKILL`; `taskkill /T /F` where `killpg` does not exist. `shares_our_group()` guards
the one way that goes badly wrong: where the child shares this process's group, signalling it would
kill the caller, so the narrow kill is taken and the teardown reports itself **unconfirmed** rather
than implying a clean stop. Consequently **an interrupted run makes no tree comparison at all** —
`treeMutated` is `None` with a basis naming the race, the same refusal `_porcelain` already makes
for a tree git will not describe.

**`head` no longer claims what it cannot.** A task gate runs *before* the task commit, so a run
executes against HEAD plus staged edits plus unstaged ones plus untracked files — two failed
retries at one HEAD were indistinguishable. `testedState` carries a `scopeDigest` over the files the
work **declares**, taken **before the first command** (a fix-in-place gate rewrites exactly those
files, so a digest read afterwards would answer a different question than the one asked), and a
`dirtyDigest` over the pre-run porcelain lines, which costs no extra git call. Both reuse
`_journal_io`'s `canonical` and `file_hash` rather than starting a second way to hash. The limit is
stated and pinned: `dirtyDigest` records *which* paths were dirty, not their contents, so editing an
already-dirty file outside the declared scope moves neither digest. It discriminates retries; it is
not a reproducible snapshot of the repository.

### `plugins/audit/scripts/manifest/audit-task.py` (v0.37.0)
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

**`add-phase "<title>" --outcome "<…>"` is the same discipline one noun up (F58)** — the writer
behind `/audit:phase add`, and the answer to the one thing nothing in this tree could do:
append a phase to a plan that already exists. `/audit:init` synthesizes a whole plan,
`/audit:propose materialize` MOVES a parked payload, `add` needs the phase to be there, and the
only other code that touched `phases[]` was the ADO pull — so the remaining options were re-running
init over finished work or hand-editing the index. It allocates the id through
`_proposals.next_phase_id` over live AND parked ids (the same allocation materialization uses, so
the two cannot hand out one id twice), initializes the conventions' new-phase template exactly
once, appends the phase LAST (written order is the plan's order), and in the sharded layout writes
the new SHARD plus the index STUB that points at it while touching no other shard — the half a hand
edit forgets. `--outcome` is required for the reason `cancel --reason` is: a phase whose success
cannot be stated in a line is a phase sign-off cannot address. The gate comes from `--gate` or from
`meta.buildCommands` keys and the report carries WHICH, including when the answer is an empty gate.
Refusals — a live id, a task id, a parked reservation, and a sharded id whose shard FILENAME an
existing phase already occupies — all land before any write, and a rollback deletes a shard the
write had just created rather than leaving a phase body the restored index no longer points at.
The `phase.add` journal row carries the outcome in its summary, because `_journal_io.DETAILS_KEYS`
is an allow-list that drops an unlisted details key in silence. One row builder now serves all
three verbs: `cancel` had its own and passed the whole viewer DICT as `actor.author`, which
`_journal_io` normalises to a null author with `via: unknown`, so every cancel row went in
anonymous and nothing on the row said so.

### `plugins/audit/scripts/usage/audit-usage.py`
`/audit:usage` — token spend, attributed, rendering its own final ASCII output (no box
drawing, no ANSI, no emoji) so the command file can print it verbatim without paying a model
to reformat a JSON rollup. With `--by phase|task|model|author|agent|day|hour|session|branch|
attr` it prints one focused table; without it, the full dashboard. `--backfill` re-reads every
transcript for the project from offset 0 and rebuilds the ledger — idempotent, and the only
path that rewrites (and therefore locks) rather than only appending.

### `plugins/audit/scripts/manifest/_manifest_io.py` + `migrate-manifest.py` + `commands/layout.md` + `commands/migrate.md` (v0.15.0)
The **sharded manifest layout**. `_manifest_io.py` is the dependency-free dual-format loader/writer:
`load_manifest` reads BOTH the single-file form and the v3 index+shards form into the same assembled
dict (so every script + hook stays format-agnostic — it's wired into all five scripts' `main()` and
`hooks/_config.in_progress_task_map`); `split_manifest`/`save_sharded` write the sharded form (index of
`{id,title,shard}` stubs + `phases/<id>.json` bodies) atomically. The index stub carries NO runtime
mirror, so a phase run writes only its shard → parallel phase branches merge with no manifest conflict.
`join_manifest`/`save_single_file` are the counterparts that write the assembled dict back out as one
file, and the one thing they own beyond the write is putting `meta.version` back down — `LAYOUT_VERSION`
is where both writers take that number from, because the layout has TWO independent readings
(`is_sharded()` over the phase stubs, and the version) and a file they disagree about has no layout at
all. `migrate-manifest.py` — driven by `/audit:layout`, of which `/audit:migrate` is the kept
legacy spelling — converts in EITHER direction — `--to=sharded|single-file`, defaulting to
sharded so every invocation predating the reverse still means what it meant — under one discipline:
validate source → refuse mid-run (unless `--force`) → backup `.bak-<UTC>` → write → re-read and check
the result both validates AND reads as the layout asked for → restore on failure. `--renumber` repairs
duplicate `BUG-` ids in either direction, `--dry-run` previews. Going to single-file then moves the
emptied shard directory aside under a `.bak-<UTC>` name — one `os.rename`, so it cannot half-apply and
nothing is deleted — as the last step, after the result has validated, because it is the only mutation
restoring the index does not undo. No lock is taken in the script: the index lock belongs to the
command driving it. Locks moved to the shared git dir(two-tier: index + per-phase-shard); ids allocate under the index lock; bug status is derived from the
linked task (so runs never write `bugs[]`). Schema bumped to v3 (phase requires only `id`/`title`; adds
`shard`/`claim`). Fully back-compat — v2 manifests keep working, migration is opt-in.

### `plugins/audit/scripts/report/render-report.py` (v0.5.0)
Manifest → self-contained `audit-report.html` + `.md` (inline CSS, zero network fetches):
phase progress bars, task tables, bug rollup, ADO links. Consumes audit-status's rollup
(single source of truth). Every manifest string is HTML-escaped — manifest content is
untrusted — and only http(s) URLs render as links (`javascript:` degrades to text).
The report's CSS/JS live as ordered feature parts under `scripts/ui/report-css/` and
`scripts/ui/report/`; `_report_ui.py` reads them at import with explicit utf-8 and assembles the same `_CSS`/`_SCRIPT` constants
byte-identically — the rendered report page stays a single self-contained file regardless.
What is left in this file after the split is `main()` — argument parsing, the manifest
read, the theme resolve, the files it writes — plus `_verdict`, and the cases that
read a report `main()` actually wrote into a temp directory. Those cases pin the emitted
DOCUMENT (its markup, its emission order, the stylesheet, the embedded script), so they can
live nowhere else: a fragment module cannot render one. `--selftest` (includes XSS cases).

### `plugins/audit/scripts/report/_report_page.py`
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

### `plugins/audit/scripts/report/_report_md.py`
The report's Markdown twin, `render_md`. It could not stay behind when `render_html` left:
the HTML page embeds this output base64-encoded as its "Download .md" payload, so
`_report_page` calls it — the single edge that makes the split two files rather than one
(`_report_page → _report_md → _report_html`/`_report_usage`, one way, no cycle). It escapes
only the Markdown metacharacters that would break a table (pipes, newlines) and passes raw
HTML through to whatever renders it; `render_html` is the hardened output for an untrusted
source. It also keeps the manifest's own machine vocabulary and the manifest's own phase
order, where the HTML segments and re-words: this table is read by GitHub and by `diff`, and
reordering it would change every diff against an earlier render for a presentational reason.

### `plugins/audit/scripts/report/_report_ui.py`
The report's CSS and inline JS, off disk as the ordered feature parts under
`scripts/ui/report-css/` and `scripts/ui/report/`, mirroring `_panel_ui.py`'s split so both
surfaces follow one convention. Each `_PARTS` tuple IS the load/cascade order, and a part
nothing joins is a feature that silently never ships. `render-report.py`
used to carry `_CSS`/`_SCRIPT` as raw-string literals (plain CSS plus `_ui_theme.TOKEN_CSS`,
and a whole `<script>...</script>` block) that no editor highlighted and no linter looked at;
this module reads the real files at import with explicit utf-8 and reassembles the same two
constants byte-identically, so the rendered report page stays one self-contained file even
though its source no longer is.

### `plugins/audit/scripts/report/_report_html.py`
Pure HTML fragment builders moved out of `render-report.py`: escaping, chips/badges, table
cells and the filter panel, over already-computed values only — no layout decisions, no usage
data, no whole-document assembly (that lives in `_report_page.render_html` /
`_report_md.render_md`, which call these dozens of times and glue the fragments together).
Every manifest value is untrusted JSON, so
each fragment routes through `e()` before it reaches the page, and `_safe_url` is the one gate
a URL passes before it may become an `href`. `render-report.py` keeps thin aliases so its
existing call sites and selftest are unchanged.

### `plugins/audit/scripts/report/_report_usage.py`
The report's Usage section, moved out of `render-report.py` as its largest single block — and
then cut into five, because at 1,477 lines it was five subjects sharing one file. What is left
here is the **order**: `_usage_section` assembles the block, and `_usage_payload` emits the one
`<script>` blob both halves read (the per-day data layer the range scoping and the heatmap
navigation both need, in a page with no server to ask). Two rules shape the whole section, which
is why they are stated here rather than in a piece: **restraint on first paint** (one dominant
chart plus three ranked lists, the rest behind a disclosure), and **every number states its
basis** (rate date, attribution coverage, sample size) or it does not render. It moved layer 4 →
layer 5, which is the whole structural cost of the cut; `_report_md` reads the Markdown twin
directly for that reason. Every name the five pieces hold is re-exported here as the same
object, so `render-report`, `_report_page` and this section's suite kept their imports.

### `plugins/audit/scripts/report/_usage_viz.py`
How the Usage section formats a number and draws a bar (layer 3) — the primitives all four other
pieces read, and nothing in it knows what a phase or an author is. The **one divide rule in two
answers** lives here: `_fill_pct` and `_hover_share` answer "there is no whole to divide by"
differently on purpose, because a bar never travels alone (its count is printed beside the track,
so an unmeasurable width draws an empty track) while a tooltip line does (so it must say `?`
rather than a confident `0%` that reads exactly like a measured one). Both go through
`_fmt.share_pct`/`fmt_share`, once per divide — **no `or 1` anywhere**, which fabricates a
denominator rather than guarding one. Also the token/cost/share wrappers over `_fmt`, the
categorical slot assignment (by NAME, so re-sorting a chart cannot repaint the survivors), `_tip`
(written once, used as both the native `title` and the styled tooltip payload), and the sparkline.

### `plugins/audit/scripts/report/_usage_load.py`
The Usage section's **only** read (layer 4): `load_usage()` turns the ledger into the dict every
other piece renders from, and returns `None` when there is no ledger — the section then renders
as nothing at all rather than as an empty frame. Deliberately not taken from `audit-status.rollup`
(the rollup is printed into a model's context, so the bulky series are computed here instead of
carried through a payload nobody reads). The comparison window is anchored to the **ledger's own
last day**, not the wall clock, so a committed example report is byte-stable across re-renders
and a shipped fixture cannot rot into a staleness warning on its own.

### `plugins/audit/scripts/report/_evidence_view.py`
The test-gate column's **only** read (layer 3): `load_evidence()` turns the evidence ledger and
the plan's `testEvidence` pointers into one view per task and per phase, and returns `None` when
the plan points at no recorded run — the badge column is then not earned, the drawer grows no
third group, and a manifest written before the field existed renders byte for byte as it did.
**The ledger is the truth and the pointer is a cache**, so every verdict rendered is read off the
row the pointer names; a pointer naming a run this checkout does not hold is its own state
(`Pointer without evidence`) rather than a silence. It hands `_evidence_io` the manifest actually
being rendered rather than the one the project config names, for `find_ledger_dir`'s reason one
directory over: resolving off the config would attribute one plan's runs to another plan's tasks.
The vocabulary and the view derivation itself live in `_report_html.py` — the badge is the STATUS
and the observations are separate marks beside it, because a gate can fail *and* rewrite the tree
and one word cannot carry both.

It also takes the **evidence boundary** as an argument and hands it, unread, to
`_status_facts.evidence_gap` — the same function `rollup` buckets the `no-test-evidence` verdict
with. That is what puts `Before recording` and `Completion undated` on the badge without letting
them disagree with the exit code: a renderer comparing `completedAt` against the boundary itself
would be a second opinion, and the direction it would drift in is the silent one, because a page
that excuses more than the gate does reads as green while the build is red. `render-report.py`
fetches one block and gives the same object to both halves; `None` is the third state and means
nobody computed one, which is exactly what every caller rendered before the parameter existed.

### `plugins/audit/scripts/report/_usage_overview.py`
What the Usage section shows on **first paint** (layer 4): the context line, the five-tile metric
strip, the notices, the one dominant trend chart, the budget block, the author chips and the three
ranked lists. The context line is where the rate basis lives — with costs shown and no date
declared it says *that* rather than falling back to the default table's date, because the ledger
prices at write time and records no vintage. The trend's axis labels live **outside** the SVG:
the columns stretch to fill the width, which scales the coordinate system non-uniformly, and the
labels once came out 49% too wide. The budget block renders nothing when no phase declares one,
and names unbudgeted phases in a footnote rather than drawing them at 0% — an unbudgeted phase is
not a phase at zero.

### `plugins/audit/scripts/report/_usage_detail.py`
Everything the section folds behind its `Detail` disclosure (layer 4): the per-author small
multiples, the calendar-month table, the risk-band routing table and its advisory, unit economics
and the cost-band note, the phase-composition stacks and the day×hour heatmap. These are the
blocks that make **claims**, so each states what it refuses to say: models are compared only
*within* a risk band (hard work is routed to the stronger model on purpose); the routing advisory
renders nothing unless the ledger's own evidence clears every gate, and carries the caveat that
it re-prices tokens a different model would not have emitted; the cost band names where its
thresholds came from, or that it is still waiting for a sample; retried spend is stated as *not*
the same as wasted spend, because the ledger buckets by hour rather than by attempt.

### `plugins/audit/scripts/report/_usage_markdown.py`
The Usage section's Markdown twin (layer 4) — not decoration and not a summary. Three light-mode
categorical slots sit under 3:1 contrast and this table **is** the documented relief, so it holds
every number the charts encode in colour, shares every gate with the HTML (a twin must not know a
month the page does not), and applies the same `<1%` floor — a `0%` here where the page says
`<1%` would make the accessibility relief the less honest of the two documents. `_report_md.py`
reads `_usage_md` from here directly rather than through `_report_usage`, which keeps the
report's Markdown renderer strictly below the Usage section's assembly instead of beside it.

### `plugins/audit/commands/panel.md` + `plugins/audit/scripts/panel/panel-server.py` (v0.13.0–v0.14.0)
`/audit:panel` opens a **localhost web UI** to manage the plugin without hand-editing JSON.
`panel.md` dispatches on its argument — bare = open (launched detached via `nohup … &`, with
stderr **appended to a per-project log** rather than sent to `/dev/null`), `stop`,
`status`, `--port <n>` — and `panel-server.py` is a single dependency-free Python-stdlib HTTP
server (the UI's HTML/CSS/JS lives as `scripts/ui/panel.html` plus the ordered parts under
`scripts/ui/panel-css/` and `scripts/ui/panel/`;
`_panel_ui.py` reads them at import with explicit utf-8 and assembles the same `UI_HTML` constant
byte-identically — the served page is still one self-contained HTML file, the source just is not.
It reuses the plugin's pure cores — `validate-manifest.py`, `validate-config.py`,
`audit-status.py`, `hooks/_config.py` — via importlib). It binds `127.0.0.1`, checks the Host header, and requires a random per-launch token
on every `/api/*` call (`X-Audit-Token`/`?t=`); it tracks **one panel per project** via a
`.claude/audit-panel.json` pidfile (open/stop/status; stale pidfiles auto-cleaned), which
carries a **build stamp** as well — written by `_write_pidfile` rather than by `serve()`, so
every pidfile this plugin writes has it and `--status` always holds both halves of the
comparison below.

**The pidfile is no longer the panel's only per-project artifact** (F99). A detached launch
that discarded stderr left a launch that FAILED looking exactly like one that succeeded and
was then stopped — no pidfile, no message, nothing on record — so the recipe appends it to
`.claude/audit-panel.log` instead, the server empties that file once it is actually
listening (anything left in it therefore belongs to a launch that never got up), and
`--status` prints its last line. `_ensure_panel_files_ignored` writes a **targeted** rule for
each of the two into `.claude/.gitignore` — never a blanket ignore, because
`audit.config.json` and `settings.json` beside them are exactly what a team SHOULD commit —
with each note on its own line, since git reads `#` as a comment only at the start of one.

**`GET /api/version` is the other build question.** The page already carries the build it was
assembled FROM; what it cannot know is what is on disk NOW, which is what turns "a control is
missing" from a guess into a sentence. `installed` is re-read per request, because an in-place
upgrade replaces `plugin.json` under a running server and that is the case worth catching, and
`ui/panel/version-banner.js` interrupts the reader when — and only when — the two disagree.
Nothing re-assembles per request: a new front end served off an old API and stamped with the
new version is a page that lies rather than one that lags, so the banner asks for a relaunch.
Four tabs:
**Settings** (a form over the WHOLE of `.claude/audit.config.json` in four groups, described
once by `SETTINGS_GROUPS`/`FIELD_HELP` in `panel-server.py` and rendered from that — the
coverage is asserted against `validate-config.py`'s own key sets, so a new config key with no
control fails the selftest), **Composition** (a compact, collapsible, **filterable** table of phases ·
tasks · per-task skills/model + per-phase review model, scaling to ~50×20, plus a discovered
"building blocks" sub-section — skills/agents/mcp — feeding the autocomplete), and **Overview**
(the live rollup + validation banner). Writes **only** config + composition fields — never
structural manifest CRUD, and never while a `/audit` run holds `<manifestPath>.lock` — validating
before each atomic save. `--selftest` covers the front-matter parser, discovery, and the server.

### `plugins/audit/scripts/panel/_panel_ui.py`
The panel's markup/CSS/JS, off disk: `scripts/ui/panel.html` plus the ordered feature parts
under `scripts/ui/panel-css/` and `scripts/ui/panel/`, whose cascade and load order are
declared once as `_ui_theme.PANEL_CSS_PARTS` and `_panel_ui._JS_PARTS`.
`panel-server.py` used to carry the whole page as one raw-string literal (~820 lines of CSS,
~28 of body markup, ~2,913 of JS, none of it Python — no editor highlighted it, no linter
looked at it). `raw_template()` reads the three files and splices css/js back into two
insertion markers in the HTML, returning the exact string `panel-server.py`'s own
`.replace()` substitution chain (theme tokens, labels, settings, field help, config enums)
still runs on — byte-for-byte, before per-request values like the audit token are filled in.

### `plugins/audit/scripts/panel/_panel_page.py`
The panel's assembled page, moved out of `panel-server.py`: the eight-substitution chain that
turns `_panel_ui.raw_template()` into what the browser gets, exporting the two names the server
imports — `UI_HTML` (the finished page wearing the default theme, which every page selftest
reads) and `UI_TEMPLATE` (the same page with the `/*__THEME_TOKENS__*/` marker intact, so
`do_GET` can dress it in the requesting project's theme per request). The order is load-bearing
and stated where it happens: the snapshot `UI_TEMPLATE = UI_HTML` sits *after* the last
substitution and *before* the theme one, and case `pg1` is what goes red if it moves. It also
holds the selftest cases that assert about the CSS and JavaScript in
`scripts/ui/panel-css/` and `scripts/ui/panel/` — three quarters of `panel-server.py` before
the split, and claims
about the front end rather than about an HTTP server. Layer 4: it reaches `usage_ledger` (L3,
for `COST_BAND_PARAMS`), `_help` (L3, selftest only), `_panel_ui`/`_panel_settings` (L2) and
`_ui_theme`/`_loader` (L1), and never `_panel_state`, `_panel_write`, `_panel_discovery` or
`panel-server` — a selftest case asserts that.

### `plugins/audit/scripts/panel/_panel_discovery.py`
Read-only discovery of which skills, agents and MCP servers this project can actually reach —
project-local, user-global, installed plugins and this repo's own plugins tree — walking the
same places Claude Code itself looks, so the panel's composition pickers offer real building
blocks instead of free-typed names that may not exist. Front-matter parsing delegates to
`_help.front_matter` rather than reimplementing it. `panel-server.py` keeps thin aliases
(`discover = _panel_discovery.discover`, etc.) so its `/api/registry` route and existing
selftest fixtures keep working unchanged.

### `plugins/audit/scripts/panel/_panel_settings.py`
Settings-shape knowledge moved out of `panel-server.py`: `FIELD_HELP`/`COMPOSITION_HELP`/
`SETTINGS_GROUPS` describe the whole Settings form once in Python rather than by hand (the
reason it exists — the `usage.*` block and most `tddReminder.*` keys had drifted out of a form
meant to make the config legible); `_META_KEYS`/`_META_API_ONLY`/`_META_FORM_KEYS`/
`_PHASE_KEYS`/`_TASK_KEYS` are the write path's security allow-list; `_settings_paths()`/
`_cfg_enums()` read the form's own bindings and the enum choices off `validate-config.py`
rather than a hand-kept copy. Sits at the bottom of the panel's import graph — must never
import `_help` or `panel-server`.

### `plugins/audit/scripts/panel/_panel_paths.py`
The floor the panel's read side stands on: `CONFIG_REL`, `_within`/`_config_path`/
`_manifest_path`/`_read_json`/`read_config`, `_declared_as_of`, the `_load` wrapper, and the
three accessors `hooks_config()`/`config_rules()`/`status_facts()`. Those three replaced
`_cores()`'s positional 4-tuple, and that is the whole reason the U3.1 split fits: the tuple
also carried `_manifest_rules` (layer 3), so a base module holding it could only sit at layer 4
— leaving nowhere for the five modules that read it, and forcing an eighth layer that would
have recorded a grab-bag accessor rather than a dependency. `hooks_config()` is the only one
that loads anything and the only one that memoizes; `_panel_state._cores()` still assembles the
same tuple in the same order for `_panel_write` and `audit-task`, which read it positionally.

### `plugins/audit/scripts/panel/_panel_viewer.py`
Who is driving the panel — the identity `usage_ledger.resolve_author` resolves, and the cache
that keeps a `git config` shell-out off every `/api/state`. Its token is a fresh stat of every
file that can decide the answer (including ones that do not exist yet, so creating a
`~/.gitconfig` invalidates) plus the environment BY VALUE, and a resolve whose files moved as it
ran is returned but not cached. `test__panel_viewer.py` slices this file between its two
git-config helpers and fails unless the origin listing runs with `--name-only` — a plain
`--list` also hands back every value, and a git config routinely holds credential helpers and
tokens.

### `plugins/audit/scripts/panel/_panel_composition.py`
The plan as the panel shows it: the phase and task rows the Composition tab edits and the
Overview lists, the bug rows (with the effective bug↔task status the rollup counts by, computed
once), the ADO card's manifest-evidence-only banner, and `areas_state` — the registry as stored
plus every tag the phases actually use, since the two disagree in both directions and each
disagreement is worth seeing.

It also carries the test-evidence half of a row: `testEvidence` verbatim as the manifest holds
it — absent means no run was recorded and never "failed" — beside `gateSource`, which says
whose gate would grade the subject and so separates "nobody has run this" from "there is
nothing here to run". `evidence_view` then ships the runs those pointers name, as positional
facts read against `EVIDENCE_FIELDS`, with the ledger's three-valued observations kept
three-valued: a tree comparison that was never made is not a clean tree, and a runner that
reports no check count has not reported zero.

### `plugins/audit/scripts/panel/_panel_policy.py`
The capability policy as the switchboard shows it: the block, the verdict for each discovered
capability (through `_policy.resolve` — the same function the guard hook calls, so the preview
cannot disagree with the guard), which rules are `dead`, which area tags are live, and whether
the guard has ever actually run here. MCP rows are stand-ins (`mcp__<server>__*`) and say so.

### `plugins/audit/scripts/panel/_panel_runstate.py`
Who is running what: the shared git-dir locks with a liveness verdict and its basis (the badge
used to claim "running" about a process it had not checked), `data_fingerprint` — the cheap
per-request stat the 5-second poll watches so a file that moved on disk hands off to
`refreshFromDisk`, and which stamps the EVIDENCE directory alongside the usage ledger through
one `newest_jsonl` rather than two copies of the same walk, so a gate that finishes mid-phase
lights its badge without a reload even when the row lands without the shard moving — and
`_gate_block`, the Plan gate card computed with the hooks' own
functions so it cannot disagree with the gate about what tier is in force. Each feed row it
serves goes through `_redacted_event` first: the `file` cell is put through
`_journal_io.repo_relative_or_token`, so an out-of-repository row reaches the browser as its
class and not as somebody's home directory. That is the same answer `audit-logs.py prune`
gives about the same rows, and this card is the one `docs/screenshots/panel-gate.png` is a
committed render of — a surface `tools/check-committed-pii.py` cannot read, because it reads
text and a PNG has none. That gap is guarded at the other end instead:
`tools/capture-screenshots.mjs` refuses to open a shutter on anything but the fixture it built
itself, and pipes the paths its fixtures will paint through
`check-committed-pii.py --scan-text` before the browser starts, so one detector vocabulary
covers the committed bytes and the committed pixels.

### `plugins/audit/scripts/panel/_panel_usage.py`
The Usage tab's payload: the ledger folded into compact positional facts the browser
re-aggregates on every filter change, rolled from hourly to daily past `_MAX_FACTS` (and saying
so rather than truncating silently), plus the small slice of plan the analytics need — read
ONCE per request for all five of its manifest-derived fields. Every branch returns
`_usage_shape`, so the no-ledger path and the populated one cannot ship different key sets.

### `plugins/audit/scripts/panel/_panel_state.py`
The panel's READ side, moved out of `panel-server.py` and split six ways at U3.1. What is left
is the journal, the help endpoints, the report export and `build_state`, which assembles one
payload out of all of them; the six modules above are where the rest went. `render_report`
stays here deliberately — it runtime-loads `render-report.py` at layer 7, the single entry in
`_deps.KNOWN_LAYER_DEBT`, and moving it into a layer-4 module would have made that recorded
edge span three layers instead of one. Nothing here writes. It re-exports all 35 names
`panel-server` and `_panel_write` alias, so the split is invisible to both — and a selftest
case asserts it never imports `panel-server` back, plus three more that no module the split
produced imports back up.

### `plugins/audit/scripts/panel/_panel_write.py`
The panel's WRITE side, moved out of `panel-server.py`: the whole path from a request body to
bytes on disk and a journal row — the write lock (`_acquire_write_lock`/`_release_write_lock`),
the change-preview machinery (`_flat_paths`, `_config_changes`, `_composition_changes`), and the
four writers (`write_config`, `apply_composition`, `write_policy`, `write_areas`). Sits above
`_panel_state` and below `panel-server`, forming the DAG `_panel_state -> _panel_write ->
panel-server`; a selftest case asserts it never imports `panel-server` back.

### `plugins/audit/scripts/config/_help.py`
The zero-token half of "what does this field mean" and "how does this actually work", backing
`/api/help` and the panel's help drawer. Field descriptions are extracted from
`schema/audit-config.schema.json`/`schema/audit-plan.schema.json` via `fields()`, never
restated by hand — a second copy of that prose is a second thing to drift, which this repo has
already shipped once. Topics are derived from the executable rule where one exists (the plan
gate's tiers from `_config.plan_gate_mode`, area resolution from `_areas`' own pinned sentences,
policy precedence from a worked `_policy.resolve` example) and are pointers, not restatements,
where the rule lives only in prose. `guide_card()` reads `agents/guide.md`'s frontmatter
so the panel cannot advertise a tool that agent does not hold. Because it owns the schema walk
that keys by DOCUMENT PATH it also owns `schema_vocab_drift()`, which holds `_manifest_vocab`'s
`KNOWN_*` sets to `audit-plan.schema.json` — the vocabulary is at layer 1 and could not reach up
for the walk, and another walk written down there would have moved the duplication rather than
removed it. This is not the tree's only schema walk: `gen-demo-manifest.schema_fields()` keys a
field by `$def` NAME instead, so an INLINE level such as `meta.ado` has no owner to attribute a
sub-key to and is outside its reach — which is why the two are not interchangeable and why
`test__manifest_vocab.py` asserts it rather than saying so.
`vocab_drift()` is the comparison on plain arguments, so its own failure modes are tested from
fixtures instead of by mutating the shipped vocabulary.

### `plugins/audit/scripts/config/_config_rules.py`
The rules for `.claude/audit.config.json` (layer 2), and the vocabulary the config is held
to. Complements `schema/audit-config.schema.json` with checks a
schema pass doesn't surface nicely (regex compilability of custom rules, positive
thresholds) and hands the control panel a machine-usable findings list. Permissive: unknown
keys are WARNINGs, not findings.

`KNOWN_ROOT` is the AUTHORITY on the root key set, and `hooks/_config.py` DEFAULTS is a proper
subset of it rather than a mirror: `policy` is accepted here and deliberately absent there,
because `_policy.py` owns that block and copying its defaults back would put a scripts-side
module on the hot path of every tool call. `config_vocab_drift()` compares the authority against
every surface that PUBLISHES it — the schema's root properties, the plugin README's
Configuration table, and those DEFAULTS — in both directions, with `OFF_ROOT` carrying the
reason for each exemption and reporting one that has gone stale. It exists because only the
other direction was ever held: the panel's Settings coverage derives its controls FROM this
validator, so "documented, therefore reachable" was checked while "runs, therefore published"
was not, and `ui` was live in four files and missing from the schema for its whole life.
`root_vocab_drift()` is the comparison on plain arguments, so its own failure modes are tested
from fixtures rather than by mutating the shipped vocabulary — the same split
`_help.vocab_drift()` is on, and the reason this lives here rather than beside that one is that
`_help` is a PEER at layer 2, so neither may import the other. It also owns the four enum tuples (`PLAN_GATE_MODES`,
`AUTHOR_MODES`, `IN_PROGRESS_POLICY`, `STRICT_MANIFEST_STATE`) the panel's Settings form
reads, so the form can never offer a value the validator rejects. Three modules needed it
and all three used to load `validate-config.py` through `_loader` — including
`_panel_settings` from LAYER 2, the deepest of the seventeen `KNOWN_LAYER_DEBT`
inversions, which is why `_panel_settings` moved up to layer 3 in the same change.

### `plugins/audit/scripts/config/validate-config.py`
The command over those rules: read the file, print `WARNING:`/`FINDING:` lines, exit 0
valid / 1 findings / 2 usage-or-unreadable. It re-exports exactly one name
(`validate_config`), and a case fails if a second one creeps back.

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
refused in the UI instead of silently dropping custom rules at hook time. `additionalProperties`
is `true` for forward compatibility, which means the schema cannot refuse a key it has never
heard of and could not report one it was never told about either —
`_config_rules.config_vocab_drift()` is what holds its root property list against the validator's
own, in both directions.

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
**Every one of them has moved**, `tests/test__output.py`'s `sc10`/`sc11` assert that end state by name,
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

**`in_json(text)`** is the needle for counting a path inside a haystack that is JSON. Suites
count an out-of-repository path in a feed file to prove a prune removed it, and
`feed.count(str(tmpdir))` is one string looked for in a copy of itself on POSIX — while on the
windows runner `str(tmpdir)` holds separators the encoder doubled on the way in, so the `== 1`
half goes red and the paired `== 0` half goes **green by describing an empty room**. The vacuous
half is the worse one, and it had been on that runner for as long as the red one. `in_json` is
`json.dumps` with its quotes taken off, so the needle is by construction what the writer put in
the file; for a path holding nothing JSON escapes it returns the text unchanged, which is why
every assertion it feeds is the assertion it already was. Only for JSON haystacks — a path
quoted in **prose** (a hook's reason, a rendered report) is spelled natively there, and
`str(path)` is already right for it. `test__gate_feed.py`'s `gf25` pins the difference on every
platform, with a fixture whose out-of-repository path carries a backslash, so the choice of
needle is no longer something only a windows leg can falsify.

**Every suite also inherits one rule it did not write.** `run()` is the only place that has
seen every label a suite produced, so it is where they are checked for being two cases wearing
one name: an id claimed from more than one `check()` call site, and a whole label printed twice.
Both arrive as named FAILING cases, because `tools/prove-gates.py` credits a mutation to the
case whose id went red — an ambiguous id defeats its `RED, WRONG CASE` verdict silently, which
is why F63 is the one defect that weakens every other proof in the tree. The rule reads the CALL
SITE rather than the occurrence count on purpose: a family driven from one loop (`t3 0 is not a
tier`, `t3 -3 is not a tier`) is one authored assertion and keeps one name, while two
hand-written cases claiming `pn10` are two. `prove-gates.py` holds the other end, refusing to
credit a row whose label names no case, or more than one.

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
  (the `bn4` now in `test__usage_bench.py`, `test_usage_ledger.py`'s `_home`), and the `_home` one is
  the reason this is stated as *dangerous* rather than merely wrong: the real function stayed
  live, the ledger walk left the fixture, and the three `discover:` cases went looking in the
  developer's own `~/.claude/usage` — the exact escape they exist to forbid.
* `globals()` / `vars()` read for INTROSPECTION, not for rebinding — "which public names does
  this module define", "is this name served here". The subject is the module, so it is
  `vars(M)`, `hasattr(M, n)`, `M.__name__`. Carried literally these answer about the test file,
  which is empty of the thing being asked about: `usage_ledger`'s `rx1` reports all 40 re-exports
  missing (loud), while the bench's `bn5` reduces to `set() - _timed == set()` and
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
  71,084-character slice where the real one was 3,747 - both figures as they stood that
  day, which is the only tense either can be stated in: the slice has since moved to
  `_panel_viewer` and shrunk, and `_harness.between()` will print its length on request.

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
and `guard-capabilities`. `KNOWN_LAYER_DEBT` did not change and the generated module map did not move.

**Batch F retired nothing either, and the reason is worth one line: none of the three lints
makes a `_loader` call at all.** Their only sibling edges are static `import _output`
(`_refs.py` once, in `__main__`; `_deps.py` twice, at module level and in `__main__`), and all
three call sites are production. `KNOWN_LAYER_DEBT` is unchanged and `_deps.py --render` is
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
python3 tools/sweep-selftests.py
# ...plus the suites that have moved out into tests/ (see §2). A migrated file still
# exits 0 on --selftest, so the loop above stays green over a suite it no longer runs.
for f in $(find plugins/audit/tests -name '*.py' | sort); do
  python3 "$f" --selftest || exit 1
done
# launcher fails LOUD without an interpreter (permissionDecision "ask" JSON):
env PATH=/nonexistent /bin/sh plugins/audit/hooks/py-launch.sh guard-edits.py ask < /dev/null

# 2. Schema + validator accept the starter AND the dogfood manifest
python3 plugins/audit/scripts/manifest/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
python3 plugins/audit/scripts/manifest/validate-manifest.py docs/audit/audit-plan.json
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
Every mutation revalidates via `scripts/manifest/validate-manifest.py`.

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
