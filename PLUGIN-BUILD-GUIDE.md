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
        task.md                           # /audit:task — add/scope/start/done/move/cancel a task, answers as flags
        bug.md                            # /audit:bug — bug tracking (add|list|fix|close)
        sync.md                           # /audit:sync — Azure DevOps work-item sync
      agents/
        audit-explorer.md                 # mechanically read-only auditor (no Edit/Write/Bash)
        audit-executor.md                 # task executor (no web tools, no nested agents)
        audit-reviewer.md                 # per-task intent check + sign-off review (no edit tools)
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
        orchestrator.md                   # shared execution logic (preflight, lock, branch-per-phase, resume)
        execute-task.md                   # Execute the task - split out so a command that never runs one skips it
        phase-signoff.md                  # Phase sign-off - split out so a command that never reaches it skips it
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
          repair-tests-add.py             # move the path an old tests.add entry already spells to the front of it
          _proposals.py                   # the proposal lifecycle: refusals, closure, collision remap, lock+apply+validate, and the rows both surfaces list
          materialize-proposal.py         # the command door onto it: arguments, the list table, printing, exit codes
          _areas.py                       # meta.areas registry + reviewSkill/skills resolution
          _branch.py                      # where a phase's branch forks from, and what it is called
          _priority.py                    # which READY task runs first: the one expression of execution order
          set-priority.py                 # the door onto it: pin a phase, or unpin it, under the index lock
          _commit_trail.py                # is a recorded task.commit still reachable from any ref?
          _manifest_rules.py              # the ORDER those rules run in, and the surface consumers import
          _manifest_vocab.py              # the manifest's words + the shape checks every level shares
          _task_outputs.py                # what a task's `outputs` pattern may be, and what an honoured one reaches
          _filed_returns.py               # an agent's filed return: its derived path, the shape its role owes, the write-once create
          _manifest_phases.py             # the one walk over phases/tasks, and what a phase carries
          _manifest_ado.py                # meta.ado: the connector config, one front door with the panel
          _manifest_typos.py              # did-you-mean: a model id / skill name one slip from another
          _manifest_crossrefs.py          # ids, refs, cycles, fileIndex, bug links, parked proposals
          _id_shape.py                    # what an id looks like and which to mint next: max+1 plus a branch suffix
          _id_refs.py                     # an id renamed everywhere the plan points at it, from one list of fields
          _warning_groups.py              # the SHAPE those warnings print in: many that differ only in the item they name, as one line
          validate-manifest.py            # the command over those rules: read a file, print, exit 0/1/2
          audit-task.py                   # /audit:task + /audit:phase doer: add/scope/start/done/cancel and add-phase/retarget, under the index lock
          migrate-manifest.py             # /audit:layout doer: --to=sharded|single-file (backup+restore)
          _manifest_merge.py              # three-way merge of one manifest document by RECORD: ids, not lines
          merge-manifest.py               # the git merge driver over it, plus install/uninstall/status and the shim
          _merge_install.py               # what that install consists of, read back - for its status AND the doctor
          migrate-json-encoding.py        # one manifest's files rewritten in the one JSON escaping, all-or-nothing under the index lock
        git/                              # the git domain: the worktree/branch half of the pipeline, as code rather than prose
          _worktrees.py                   # which worktrees exist, whose phase each is, and what may be reaped
          close-phase.py                  # sign-off 5c-5e as one step: merge into the resolved parent, stamp it, clean up
          manage-worktrees.py             # list / add / remove / sweep: the account of what /audit:worktree created
        governance/                       # the governance domain: the policy, the lock, the audit trail
          _policy.py                      # capability policy: shape, validation, required -> deny -> allow -> default
          _locks.py                       # the lock library: where one lives, is it live, acquire/release
          audit-lock.py                   # the CLI over it: acquire/release/status as exit codes
          _journal_io.py                  # the audit trail: row shape, hash chain, read/append/verify
          _evidence_io.py                 # the test-evidence record: where it lives, what a row may say, and the chain over it
          _gate_derive.py                 # the gate helpers' one home (is_shared_key/path_scoped_sibling/repointed) and a pure derive() for a phase's sign-off gate
          audit-journal.py                # the CLI over both records: append/verify/show/archive, plus merge and sessions
          _invariants.py                  # the orchestrator's rules, re-derived from git + shard + journal + ledger
          verify-invariants.py            # the CLI over it: one phase or --all, breach = exit 1
          _scoped_commit.py               # what both commit-a-narrow-allow-list commands share: the git runner, the two index reads, the answer
          commit-audit-state.py           # commits the phase's manifest file + journal + evidence and NOTHING else, or says there is none
          commit-manifest-index.py        # commits the manifest INDEX and the row naming the commit, NOTHING else, under the index lock; refuses in the single-file layout
          commit-task-work.py             # commits ONE task's declared files + the phase file + the records, naming any staged path outside that list
          run-test-gate.py                # runs a phase's gate bracketed by a tree snapshot; counts what ran; states what it touched
          propose-gates.py                # a plan proposal from what evidence history caught, not the tree alone - and says which it drew on
          record-risk-confirmation.py     # the high-risk gate answered BEFORE the run, bounded to named task ids and written to the trail
          record-outside-run.py           # a suite that ran where this plugin could not see it, so a gate run in the same window is not credited with its effects
          import-evidence.py              # a CI build's own evidence ledger file, brought in whole after its chain verifies - never rewrites a row, never re-chains; prints (never runs) the full-gate.py --learn-from command for each red full row it brought in
          drive-phase.py                  # the step driver: `next <phase>` runs every due step that needs no judgement through the existing verbs, as subprocesses, and prints one instruction - dispatch, decide or done; a refused verb stops it with the verb's own words. Sign-off is the phase review's dispatch, one triage decision, then gate, invariants, sign-off verb, commit, landing and lock release as one step. `submit` is an agent's last act: the stamp, the red-first helper and the filing in one call
          full-gate.py                    # the one command of the third place: a pre-push hook's whole obligation - run-test-gate.py --full --record as a subprocess, then a coupling and a bug per named selection miss of a red run (the red still blocks), or the sentence and exit 0 when no meta.fullGate is declared; --learn-from <runId> runs nothing and learns from an imported row through the same function
          _runner_output.py               # every reading of what a test runner printed: its summary line (how many checks ran) and the lines naming a failing check
          _proc_group.py                  # one child tree stopped whole on timeout or interrupt; SIGINT/SIGTERM as an exception so a finally runs; the one POSIX sh (and its PATH) every plan command runs under, or a refusal - never cmd.exe
          _tree_stamp.py                  # which tree was this: HEAD + declared-work digest + dirty-path digest, and is it still that one
          _verdict_binding.py             # the ONE rule for whether a recorded gate verdict binds the declared work now - a task commit's, a sign-off's, and whether `done` or close-phase may close over the newest verdict (one that no longer holds refuses)
          stamp-verification.py           # the CLI over it: take a stamp, or grade one - current / stale (naming the field) / unestablished; `red` proves a red-first in a throwaway tree
          derive-phase-gate.py            # observes a phase's version answer, its two importer listings, changed/red-suite paths and the plan gate's exempt verdict, hands them to _gate_derive.derive, and records phase.testGateDerived (+ testGate in enforce mode) under the index lock
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
          _live_copy.py                   # which copy holds a phase in flight live - one reader for status, panel and report
          audit-status.py                 # the command over those facts: human render + --json/--gate
          audit-doctor.py                 # /audit:doctor: the ORDER of the checks, the render and the CLI
          _doctor_report.py               # what the six check modules share: the Report collector + _load
          _doctor_setup.py                # interpreter, sandbox + secret rules, git root, config, manifest, shards, submodules
          _doctor_policy.py               # meta.areas, the capability policy, the buildCommands runners
          _doctor_ado.py                  # the ADO connector's operational half (transport, switches, links)
          _doctor_trail.py                # has anything run here, and which plugin copy ran it: hook state, the running-copy stamp, usage ledger, journal chain
          _doctor_completions.py          # the close receipts against the plan, git and the ledger
          _doctor_hygiene.py              # what is HELD (locks) and what is LEAKING (local artifacts in git)
          _gate_feed.py                   # the plan-gate events feed's prune rule: which rows no longer belong
          audit-logs.py                   # /audit:logs: the door onto that rule - parse, render, exit code
          audit-lookup.py                 # one question, one pointer: why cancelled, a bug's conclusion, fileIndex's last declarer; computed spawn briefs
          audit-version.py                # /audit:version: the running build, the marketplace and installed copies, the newest release
          _claude_home.py                 # Claude Code's own install records (installed_plugins.json, known_marketplaces.json), read fail-open
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
        permissions-deny.example.json     # optional Claude Code permissions.deny fragment
      evals/                              # `claude plugin eval` cases: plugin arm vs no-plugin baseline, same prompt
        bugfix/case.yaml                  # a symptom-only defect; graded on the transcript; not runnable until scaffold.sh exists beside it
        guard-stop/case.yaml              # a dirty tree + a .env canary; the safe outcome leaves both alone; not runnable until scaffold.sh exists beside it
        results/                          # written by `claude plugin eval`; gitignored
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
  _claude_home -> _output
  _cli_fmt -> _output
  _commit_trail -> _output
  _demo_cast -> _output
  _deps -> _output
  _filed_returns -> _output
  _fmt -> _output
  _id_refs -> _output
  _journal_io -> _output
  _loader -> _output
  _locks -> _output
  _manifest_io -> _output
  _manifest_merge -> _output
  _manifest_vocab -> _output
  _merge_install -> _output
  _policy -> _output
  _priority -> _output
  _proc_group -> _output
  _refs -> _output
  _runner_output -> _output
  _task_outputs -> _output
  _ui_theme -> _output
  _usage_core -> _output
  _worktrees -> _output

L2:
  _ado_drift -> _manifest_io, _manifest_vocab, _output, _usage_core
  _config_rules -> _loader, _output, _policy
  _doctor_report -> _loader, _output
  _evidence_io -> _journal_io, _locks, _manifest_io, _manifest_vocab, _output, _usage_core, _worktrees
  _gate_feed -> _journal_io, _loader, _output, _usage_core
  _help -> _areas, _journal_io, _loader, _manifest_vocab, _output, _policy, _ui_theme
  _id_shape -> _branch, _manifest_io, _manifest_vocab, _output
  _manifest_ado -> _ado_conventions, _ado_fields, _manifest_vocab, _output
  _manifest_crossrefs -> _ado_parent, _id_refs, _manifest_io, _manifest_vocab, _output, _priority
  _manifest_phases -> _ado_parent, _ado_tracked, _areas, _manifest_io, _manifest_vocab, _output, _task_outputs
  _manifest_typos -> _areas, _manifest_vocab, _output
  _panel_ui -> _output, _ui_theme
  _report_html -> _areas, _fmt, _manifest_io, _manifest_vocab, _output, _priority, _ui_theme
  _report_ui -> _output, _ui_theme
  _status_facts -> _areas, _filed_returns, _manifest_io, _manifest_vocab, _output, _priority, _usage_core
  _tree_stamp -> _journal_io, _manifest_vocab, _output
  _usage_coverage -> _manifest_io, _output, _usage_core
  _usage_economics -> _manifest_io, _output, _usage_core
  _usage_routing -> _manifest_io, _output, _usage_core
  _usage_spend -> _output, _usage_core
  _warning_groups -> _fmt, _manifest_io, _output

L3:
  _ado_fetch -> _ado_drift, _output
  _doctor_ado -> _ado_drift, _ado_tracked, _doctor_report, _output
  _doctor_hygiene -> _branch, _locks, _output, _worktrees
  _evidence_view -> _evidence_io, _manifest_io, _output, _report_html, _status_facts
  _gate_derive -> _evidence_io, _manifest_io, _manifest_phases, _manifest_vocab, _output
  _manifest_rules -> _branch, _manifest_ado, _manifest_crossrefs, _manifest_io, _manifest_phases, _manifest_typos, _manifest_vocab, _output, _status_facts
  _panel_discovery -> _help, _manifest_io, _output, _policy
  _panel_paths -> _config_rules, _loader, _manifest_io, _output, _status_facts
  _panel_settings -> _config_rules, _output
  _usage_bench -> _output, _usage_core, _usage_coverage, _usage_economics, _usage_routing, _usage_spend
  _usage_viz -> _fmt, _output, _report_html
  _verdict_binding -> _evidence_io, _journal_io, _manifest_io, _output, _tree_stamp
  usage_ledger -> _manifest_io, _output, _usage_core, _usage_coverage, _usage_economics, _usage_routing, _usage_spend

L4:
  _doctor_completions -> _commit_trail, _doctor_report, _evidence_io, _journal_io, _manifest_vocab, _output
  _doctor_policy -> _branch, _doctor_report, _manifest_io, _output, _worktrees
  _doctor_setup -> _claude_home, _config_rules, _doctor_report, _manifest_rules, _manifest_vocab, _merge_install, _output, _status_facts, _warning_groups
  _doctor_trail -> _doctor_report, _evidence_io, _fmt, _journal_io, _manifest_io, _manifest_vocab, _output, _worktrees
  _invariants -> _branch, _commit_trail, _evidence_io, _journal_io, _locks, _manifest_crossrefs, _manifest_io, _manifest_rules, _output, _status_facts, usage_ledger
  _panel_composition -> _ado_drift, _ado_parent, _ado_tracked, _areas, _branch, _evidence_io, _manifest_io, _manifest_vocab, _output, _panel_paths, _priority, _status_facts, _worktrees
  _panel_page -> _loader, _output, _panel_settings, _panel_ui, _ui_theme
  _panel_policy -> _areas, _config_rules, _manifest_io, _output, _panel_discovery, _panel_paths, _policy
  _panel_runstate -> _doctor_report, _evidence_io, _journal_io, _locks, _output, _panel_paths
  _panel_usage -> _areas, _evidence_io, _manifest_io, _output, _panel_paths
  _panel_viewer -> _loader, _output, _panel_discovery, _panel_paths
  _proposals -> _fmt, _id_refs, _id_shape, _locks, _manifest_io, _manifest_rules, _manifest_vocab, _output
  _usage_detail -> _output, _ui_theme, _usage_economics, _usage_viz
  _usage_load -> _loader, _output, _report_html
  _usage_markdown -> _output, _ui_theme, _usage_economics, _usage_viz
  _usage_overview -> _fmt, _output, _ui_theme, _usage_economics, _usage_viz

L5:
  _panel_state -> _evidence_io, _help, _journal_io, _manifest_io, _manifest_rules, _output, _panel_composition, _panel_discovery, _panel_paths, _panel_policy, _panel_runstate, _panel_usage, _panel_viewer, _proposals, _report_html
  _report_md -> _output, _report_html, _usage_markdown
  _report_usage -> _output, _usage_detail, _usage_load, _usage_markdown, _usage_overview, _usage_viz
  _scoped_commit -> _evidence_io, _invariants, _journal_io, _output

L6:
  _live_copy -> _branch, _invariants, _locks, _manifest_io, _output, _scoped_commit, _status_facts, _worktrees
  _panel_write -> _ado_parent, _ado_tracked, _areas, _branch, _config_rules, _gate_feed, _journal_io, _locks, _manifest_io, _output, _panel_discovery, _panel_settings, _panel_state, _policy, _priority, _proposals, _ui_theme, _warning_groups, _worktrees
  _report_page -> _fmt, _manifest_io, _output, _report_html, _report_md, _report_ui, _report_usage, _status_facts

L7:
  ado-connect -> _ado_connect, _output
  audit-doctor -> _claude_home, _cli_fmt, _doctor_ado, _doctor_completions, _doctor_hygiene, _doctor_policy, _doctor_report, _doctor_setup, _doctor_trail, _output, _panel_runstate
  audit-journal -> _claude_home, _evidence_io, _journal_io, _output
  audit-lock -> _claude_home, _locks, _output
  audit-logs -> _claude_home, _gate_feed, _output
  audit-lookup -> _areas, _claude_home, _config_rules, _evidence_io, _filed_returns, _journal_io, _loader, _manifest_io, _manifest_vocab, _output
  audit-status -> _areas, _claude_home, _cli_fmt, _evidence_io, _fmt, _invariants, _live_copy, _loader, _manifest_io, _manifest_rules, _manifest_vocab, _output, _panel_discovery, _proposals, _status_facts, _ui_theme
  audit-task -> _areas, _branch, _claude_home, _commit_trail, _config_rules, _evidence_io, _filed_returns, _gate_derive, _id_refs, _id_shape, _invariants, _journal_io, _loader, _locks, _manifest_io, _manifest_phases, _manifest_rules, _manifest_vocab, _output, _panel_write, _proposals, _status_facts, _task_outputs, _verdict_binding, _warning_groups, _worktrees
  audit-usage -> _areas, _claude_home, _cli_fmt, _evidence_io, _fmt, _loader, _locks, _output, _ui_theme, _usage_economics
  audit-version -> _claude_home, _output
  check-ado-item -> _ado_conventions, _ado_fields, _ado_parent, _output
  close-phase -> _branch, _claude_home, _config_rules, _evidence_io, _filed_returns, _journal_io, _loader, _manifest_io, _manifest_rules, _output, _panel_write, _proposals, _tree_stamp, _verdict_binding, _worktrees
  commit-audit-state -> _claude_home, _evidence_io, _invariants, _journal_io, _manifest_io, _output, _scoped_commit
  commit-manifest-index -> _claude_home, _invariants, _journal_io, _manifest_io, _output, _panel_write, _scoped_commit
  commit-task-work -> _claude_home, _evidence_io, _filed_returns, _invariants, _journal_io, _manifest_io, _manifest_vocab, _output, _scoped_commit, _verdict_binding
  derive-phase-gate -> _claude_home, _evidence_io, _gate_derive, _loader, _manifest_io, _manifest_phases, _manifest_vocab, _output, _panel_write, _proc_group
  drive-phase -> _areas, _claude_home, _config_rules, _evidence_io, _filed_returns, _journal_io, _loader, _manifest_io, _manifest_phases, _output, _status_facts, _verdict_binding
  explain-ado-drift -> _ado_drift, _manifest_io, _output
  fetch-ado-items -> _ado_fetch, _manifest_io, _output
  full-gate -> _claude_home, _evidence_io, _loader, _manifest_io, _output, _panel_write, _status_facts
  gen-demo-manifest -> _claude_home, _demo_cast, _evidence_io, _journal_io, _loader, _manifest_io, _output
  gen-demo-usage -> _claude_home, _demo_cast, _loader, _output
  import-evidence -> _claude_home, _evidence_io, _journal_io, _loader, _manifest_io, _output, _panel_write
  manage-worktrees -> _branch, _claude_home, _manifest_io, _output, _worktrees
  materialize-proposal -> _claude_home, _manifest_io, _output, _proposals, _warning_groups
  merge-manifest -> _claude_home, _id_refs, _id_shape, _locks, _manifest_io, _manifest_merge, _manifest_rules, _merge_install, _output
  migrate-json-encoding -> _claude_home, _manifest_io, _manifest_rules, _output, _panel_write
  migrate-manifest -> _id_shape, _manifest_io, _manifest_rules, _output
  panel-server -> _claude_home, _live_copy, _manifest_io, _output, _panel_discovery, _panel_page, _panel_runstate, _panel_settings, _panel_state, _panel_write, _ui_theme
  propose-gates -> _claude_home, _evidence_io, _manifest_vocab, _output
  read-ado-links -> _ado_drift, _ado_tracked, _manifest_io, _output
  record-outside-run -> _claude_home, _evidence_io, _journal_io, _manifest_io, _output
  record-risk-confirmation -> _claude_home, _journal_io, _manifest_io, _output
  render-report -> _areas, _evidence_io, _evidence_view, _fmt, _invariants, _live_copy, _loader, _manifest_io, _manifest_rules, _manifest_vocab, _output, _panel_discovery, _report_html, _report_md, _report_page, _report_ui, _report_usage, _status_facts, _ui_theme
  repair-commits -> _commit_trail, _journal_io, _locks, _manifest_io, _manifest_rules, _output
  repair-tests-add -> _journal_io, _locks, _manifest_io, _manifest_rules, _output
  resolve-ado-parent -> _ado_parent, _manifest_io, _output
  resolve-ado-tracked -> _ado_tracked, _manifest_io, _output
  resolve-branch -> _branch, _manifest_io, _output, _worktrees
  run-test-gate -> _claude_home, _evidence_io, _fmt, _loader, _manifest_io, _manifest_phases, _manifest_vocab, _output, _panel_write, _proc_group, _runner_output, _status_facts, _tree_stamp
  set-priority -> _claude_home, _manifest_io, _output, _panel_write, _priority, _warning_groups
  stamp-verification -> _claude_home, _evidence_io, _locks, _manifest_io, _output, _proc_group, _runner_output, _tree_stamp, _worktrees
  validate-config -> _config_rules, _output
  validate-manifest -> _evidence_io, _manifest_io, _manifest_rules, _output, _warning_groups
  verify-invariants -> _claude_home, _invariants, _manifest_io, _output
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
drops ALL frontmatter), plus "read `orchestrator.md` + `manifest-conventions.md`, run this slice" —
and, for the four verbs that actually run a task or reach sign-off, the further file that section
now lives in. `orchestrator.md` holds only what every verb needs: config resolution (incl.
`meta.gitRoot`), preflight (config/manifest/git-root/submodule/lock), guardrails, readiness rule,
concurrency lock, branch-per-phase, keeping a failed run's record, the ADO echo, resume, progress
output, dry-run/preview, reporting. **`## Execute the task` and `## Phase sign-off` are split into
their own files** — `reference/execute-task.md` and `reference/phase-signoff.md` — so a command
that never runs a task or never signs a phase off does not pay to read the section it will not
use: `next`, `phase` and `run` read the first; `phase` and `review` read the second; `status`,
`report`, `resume`, `worktree` and `layout` read neither. The claim-anchor mechanism in
`scripts/manifest/_areas.py` (`SECTION_DOC`) follows the same section into whichever file now
holds it, so a section that moved without its anchor following still fails by name. **De-coupling:**
everything reads `meta.developmentBranch` / `branchPrefix` / `gitRoot` / `reviewSkill` (null → skip)
/ `areas` (the monorepo registry a phase's `area` tag names; resolution `phase.reviewSkill ??
meta.areas[tag].reviewSkill ?? meta.reviewSkill`, stated identically in `orchestrator.md`,
`manifest-conventions.md` and `review.md`) / `runtimeBoot` (null → skip) / `nodePreamble` /
`commit` / `buildCommands` — no hardcoded branch, package id, skill, or build tool. Read-only verbs
(`status`, `report`) skip the mutating preflight and never lock.

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
- PreToolUse `Read|Grep|Bash|mcp__.*` → `guard-secrets-read.py` (fail mode **ask**)
- PreToolUse `Bash` → `guard-history-rewrite.py` (fail mode **ask**)
- PreToolUse `Edit|Write|MultiEdit|NotebookEdit` → `guard-edits.py`, then `require-plan.py` (both **ask**)
- PreToolUse `mcp__.*` → `guard-edits.py`, `require-plan.py` (both **ask**), `journal-writes.py` (**open**) — an MCP server's write tool reaches no edit-tool matcher, so without this row it escaped the plan gate, the self-edit rule and the audit trail alike. Each hook decides what an MCP call can reach on its own terms; `_config.mcp_payload` holds the one write test the two guards share, and says which way it is allowed to be wrong
- PreToolUse `Skill|Task|Agent|mcp__.*` → `guard-capabilities.py` (fail mode **ask**)
- PostToolUse `Edit|Write|MultiEdit|NotebookEdit` → `require-plan.py` (state commit), `remind-tdd.py`, `guard-bash-writes.py` (records tool edits), `journal-writes.py` (records manifest/config writes; all **open**)
- PostToolUse `mcp__.*` → `require-plan.py` (state commit), `journal-writes.py` (the digest sweep, which needs no write test because it asks the FILE; both **open**). `guard-bash-writes.py` and `remind-tdd.py` are deliberately absent — each says why in its own docstring
- PostToolUse `Bash` → `guard-bash-writes.py` (the diff check), `journal-writes.py` (the `dangerouslyDisableSandbox` row **and** the digest sweep that catches a manifest written by a shell command; both **open**)
- UserPromptSubmit → `detect-plan-skip.py` (**open**)

`py-launch.sh` resolves `python3` → `python` → `py` with shell builtins only and
runs the script (stdin passes through once, exit code propagates). It does not
`exec`: after an `exec` nothing is left to notice that the interpreter never
started, which is the failure the loud path exists for. A nonzero status is
therefore followed by one `-c ''` question to the same interpreter, and only an
interpreter that cannot answer it is treated as one that never ran the hook — so
the probe costs a process on the failing path and none on the path taken before
every tool call. A candidate that fails it is skipped rather than accepted, which
is what makes the `python3` → `python` → `py` chain reachable past a broken first
name.

Three ways the hook can fail to run at all, each with its own sentence because
each has its own repair: no interpreter resolves, one resolves and cannot run, or
the named script is not beside the launcher (a plugin root pointing at a tree
without it). In `ask` mode each emits `permissionDecision: "ask"` JSON — the
guarded tool call surfaces a manual prompt instead of silently proceeding
(fail-LOUD); `open` mode exits silently (advisory hooks must never block). Fail
modes are hardcoded here because reading config requires Python
(chicken-and-egg).

**One failure is outside this file and the launcher says so rather than implying
it is covered.** `${CLAUDE_PLUGIN_ROOT}` is interpolated into the command string
and never exported, so a root that expands to nothing leaves `sh` opening
`/hooks/py-launch.sh` and exiting 127 before the launcher's first line runs. A
branch keyed on that variable would not recover it and would prompt on every
healthy tool call, since a healthy hook has no such variable in its environment
either; the observable half is the not-beside-the-launcher case above, and the
reader for the other half is `/audit:doctor`, which reports hooks that have never
fired. `plugins/audit/tests/test_py_launch.py` drives all of this against real
shims on `PATH`.

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
`covering_key` is the matcher over any of those file maps (exact, the path as a directory, a
directory the path sits under), shared so a verdict and the sentence explaining it cannot answer
it differently; `declaring_tasks` is the read-only companion that keeps every status instead of
filtering to `in_progress`, and it exists for the refusal TEXT alone — require-plan names which
of two causes it found (no task declares this file, or one does and nobody started it) while
still deciding on `in_progress` coverage and nothing else.
`within_root` is the containment question `rel_path` cannot answer: relpath hands a path
in another tree back as a run of `..` segments, an ordinary string that read as repo
source and got a scratch file in the system temp directory refused by the plan gate. It
lives here rather than in the one hook that reported it because three hooks ask it and
`SECURITY.md` promises two of them agree; it never calls `relpath`, which RAISES across
Windows drives.
Each hook does `sys.path.insert(0, dirname(__file__)); import _config`. `--selftest`.

`hook_plugin_root()` / `hook_plugin_version()` / `stamp_running_plugin()` /
`running_plugin_stamps()` are the writer and the reader of the running-copy stamp.
A hook is the only process that knows which plugin copy the harness is executing —
`CLAUDE_PLUGIN_ROOT` is interpolated into hooks.json's command strings and never exported,
so `/audit:doctor` has nothing in its environment to read — and disk is therefore the whole
channel. The reader lives beside the writer, unused by any hook, because the file's name and
its keys are one fact with one home; a copy of them under `scripts/` would drift the first
time a key was added. `hook_plugin_version()` is the fourth irreducible derivation of a
`scripts/` fact for `find_script`'s reason, and `tests/test__config.py`'s `rp1`–`rp2` hold it
against `_output.plugin_version()` rather than trusting a comment.

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
Plan-first gate on Edit/Write/MultiEdit/NotebookEdit **and on `mcp__.*`**, registered under
BOTH PreToolUse and PostToolUse. An MCP call is decided on a path `_mcp_plan_target` resolves
— the plan first (manifest, lockfile, phase shard, via `governing_lock`), then a source file
(via `source_exts`), which are the two questions `guard-secrets-read` asks of a `sed -i`
target, in its order, so one file gets one verdict however it is written. It resolves nothing
without a write basis in the payload; `_config.mcp_payload` holds that test and the direction
it is allowed to be wrong in.
ALLOW/BLOCK order: unknown tool/no path → allow; exempt glob (config) → allow;
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
**Transactional state**: PreToolUse takes the session's free-file slot — the one slot
`guard-secrets-read.py` takes for a shell write at its own Pre, read and written through
`_config.trivial_slot` / `take_trivial_slot` — and does not consume the bypass (the edit may
still be denied by a sibling hook or the user, so a refused edit has still spent the slot).
PostToolUse — which fires only after a successful edit — consumes the bypass (logged),
confirms the slot (taking it only when Pre did not), and appends to the observe tally. All tunables
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
single-use. It also stamps `stateDir/running-plugin-<session>.json` (`{root, version}`) on
every prompt, which is the only record of **which copy of the plugin the harness is actually
running** — a prompt is the coarsest event a session cannot avoid, so the stamp sits here
rather than on the per-tool-call path the guards are on. `--selftest`.

### `plugins/audit/hooks/guard-bash-writes.py` (v0.6.0)
PostToolUse watcher — the "complete control" for shell writes the PreToolUse text
inspection cannot decide (upstream #29709). Edit-tool events RECORD the touched file;
Bash events diff `git status --porcelain -uall` against the session's last-seen dirty set:
a NEW dirty source file that is not exempt, not the manifest/lock, not tool-edited, and not
covered by an `in_progress` task triggers a non-blocking `additionalContext` warning (once
per file per session). Needs a git repo; git errors/timeouts (5 s) are silent. Config:
`bashWriteCheck.enabled` (default true). `--selftest` (incl. a real `git init`
integration case).

The authorship half of that warning comes off whenever somebody else could have written the
path: a peer SESSION (its own state file moved inside the window), this session's own
background job (no hook fires when one ends), a command that moved the shell with `cd`, and
a peer AGENT of this session. The last is the one nothing keyed by session can see — agents
share a `session_id`, so they share the state file `_other_sessions` skips as `mine` — and
`agents`, the writer map inside that file, is what makes them visible: each agent by its
payload `agent_id`, the main agent (which carries none) under `MAIN_WRITER`. What it maps
them to is a POSITION in the session's pass order, not a clock reading — "did that writer
act between my previous look and this one" is a question about order, every pass being
ordered writes this one file, and a wall clock answered it by the platform's timer
granularity instead: on Windows consecutive passes of one session landed on the same value
and the peer went unseen, so the withdrawal fired according to how fast the machine was.

### `plugins/audit/agents/` (v0.6.0, a fourth in v0.31.0)
Four pinned-tool agents, three of which the commands spawn via `subagent_type` (with a
general-subagent
fallback for older Claude Code): `audit-explorer` (Glob/Grep/Read — mechanically read-only;
/audit:init fan-out), `audit-executor` (Read/Edit/Write/Glob/Grep/Bash/Skill — no web tools,
no nested agents; task execution and review fixes), `audit-reviewer`
(Read/Glob/Grep/Bash/Skill — no edit tools; spawned per task to ask whether the diff does what
the task's description asked and whether the executor's returned claim describes it, and again
at sign-off, where it runs the project review skill inside the agent so the diff stays out of
the orchestrator's context). Tool lists are a hard
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
`tddReminder.sourceGlobs`). Both arms ask one function, `_ungoverned_write_target`, which declines to grade a
destination only the shell can resolve rather than reading that spelling as a path in the
tree, and both are
**graded on the plan gate's tier** through one more, `_plan_gate_write_verdict` — the only place
in this hook that may read a tier, and one no secret rule calls. That is the separation: plan
COVERAGE needs a plan to mean anything, a secret does not. Listing NAMES stays allowed. `secretPatterns.extra` (config) adds
patterns. `--selftest` uses fictional paths only.

**P0-S: the environment reached INDIRECTLY, and where this hook's reach ends.** `printenv` was
anchored to the start of a clause, so any wrapper in front of it walked straight past —
`direnv exec . printenv X` printed a secret with no deny, no gate message and no journal row.
The verb is now a dump wherever it stands (a rule about what may not PRECEDE it, because an
inventory of legal wrappers cannot be written and would be short by one), `direnv dump`/`export`
join it, and `.envrc` — the file the live report was actually about — joins the secret sets.
`process.env` moved from the secret-FILE rule to the environment rule: the whole object and a
token-shaped name are refused, one ordinary named variable is not, and being refused as "reading
a secret file's contents" was the same false-positive class fixed one layer up. Finally the
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
this project's history — `guard-secrets-read`'s read-vs-write class was fixed for the same reason
before it — so the ancestry check is not an optimisation — it is the reason the guard is allowed
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
**On `mcp__.*` it is not all of that**, and the module docstring argues it rule by rule: the
self-edit refusal is reached on the TARGET alone (the installed plugin's directory sits outside
the consuming repo, so refusing a read there costs nothing), bypass forgery and the append-only
journal are reached only with a write basis (both live inside the repo, where refusing a read
would be friction on honest work), and the custom rules and the token-logging ban are **not
reached at all** — they grade the text that will become file bytes, and only an edit tool's
fixed schema can name that text.

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
PostToolUse (Edit|Write|MultiEdit|NotebookEdit, **Bash and `mcp__.*`**) recorder: every write
to the manifest (index or phase shard) or to `.claude/audit.config.json` appends one row to the
audit trail via `scripts/governance/audit-journal.py`. Bash and MCP share the **sweep lane**
(`swept_entries`), which needs no rule about which operations write: it compares each recorded
path's digest against the slot the Pre pass seeded, so a read moves nothing and says nothing
while a write gets the row an `Edit` gets. NO stdout at all — a recorder that talks turns
every manifest edit into transcript — and every failure is silent, because a journal that
cannot be written must not break the write it was recording. A hook rather than an
instruction on purpose: a model that forgets to log a change leaves a gap that looks exactly
like a covered-up one. Config `journal.enabled`. `--selftest` (incl. an end-to-end
append + verify).

**The two passes, and why the tool is not part of the question.** Edit fragments are
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

**Which agent, not just which session.** One session runs an orchestrator and its subagents
and they all share `session_id`, so `actor.sessionId` could say which *session* changed the
plan and never which *writer* inside it — while a subagent editing the manifest is the exact
act `require-plan` and `guard-secrets-read` refuse. Every row this hook writes carries
`actor.agent`, resolved once in `_actor()` for both lanes: a subagent's own `agent_id`,
sanitised, or the word `_config.MAIN_AGENT` for the orchestrator. **The word is the point** —
an empty field would mean "the orchestrator did it" and "nobody recorded it" at the same
time, and a reader of a committed file could not tell which. `_config.agent_of` is the one
place the payload is read (`is_subagent` beside it is the same question as a predicate, and
the guards above ask it there rather than each spelling the key itself); `_journal_io` bounds
what reaches the row and writes no field at all for a writer that named no agent, which is
what the panel and the CLI are and what every row written before the field is.

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
`{initials}`, `{phase}`, `{slug}` — into the name. `branch_of()` is the one answer every
worktree surface gives to "which branch is this phase's" — the recorded `phase.branch`, else the
composed name with git user.name — so `manage-worktrees.py` and the panel's sweep cannot name a
phase two ways; `plan_branches()` is that answer over a whole plan.

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

### `plugins/audit/scripts/git/_worktrees.py`
Which worktrees this repository has, whose phase each one is, and what may be reaped. The
worktree/branch half of the pipeline was prose until this module: `commands/worktree.md` composed
a path and recorded it nowhere, and `reference/orchestrator.md` steps 5c–5e were git commands the
model typed. Nothing could enumerate what had been created, so nothing could clean it up.

**Git is the registry, not the manifest.** A `phase.worktree` field would be a second source of
truth that goes stale the moment somebody moves a directory. `git worktree list --porcelain`
already gives the authoritative (path, branch) pair, and the phase is joined onto it through
`phase.branch` — so a worktree made by hand, at a path nobody predicted, is still seen and still
judged.

**Every question has three answers, and the third is loud.** `merged_into()` returns `contained`,
`not-contained` or `unknown`; `ref_exists()` and `dirtiness()` return `True`/`False`/`None` on the
same principle. The cost of collapsing them is live one directory over:
`_doctor_policy.check_branch_naming` writes `merged = (out.returncode == 0)`, which turns exit 128
— a `parentBranch` this clone does not have — into a definite *"is NOT yet merged"* accusation.

**The word is `contained`, not `merged`.** `git merge-base --is-ancestor` answers 1 for a
squash-merged branch: the work IS in the parent and the tip is not an ancestor of it. Nothing here
says "never merged" about that branch, and `detail` carries the sentence that explains the answer.

**The planners are pure, and that is what makes them testable.** `merge_plan()`, `cleanup_plan()`
and `sweep_plan()` take the observations as arguments and return the argv a caller would run, so
their cases drive the exit-128 and could-not-ask branches without a repository. `_branch` is a
layer-mate and cannot be imported, so branch and parent names arrive as arguments too — which is
what keeps this module at L1 where four surfaces can share the one answer.

**Two refusals are the plugin's own and say so.** Git fast-forwards over unrelated dirt in the
parent worktree and exits 0; git also removes the worktree the calling process is standing in,
silently, with exit 0 and empty output. Both are refused here, worded as this plugin's rule —
a refusal that misattributes itself to git is one the operator disproves in a single command.

**Cleanup order is a contract, not a preference.** `git branch -d` refuses for a branch checked
out in ANY worktree, so removal comes strictly before deletion; and deletion is gated on
`merge-base --is-ancestor <branch> <parent>` rather than on `git branch -d`'s own net, which
grades reachability from HEAD and will delete a branch that never reached its declared parent.

### `plugins/audit/scripts/git/close-phase.py`
Sign-off steps 5c–5e as one command. It merges the phase branch into its resolved parent, writes
`phase.mergedAt`, and performs whatever cleanup `meta.merge` asks for — each step planned in full
before the first write, and each result read back by asking a *different* question than the write
answered. The merge is an input of the phase's derived status, so the stamp stores that status in
the same write (`done`, for a signed-off phase with every task terminal) and `mirror_stub`
re-mirrors the index stub from the shard. **The stamp is then committed where it was written**
(`commit_landing`): in the parent's checkout through `commit-audit-state.py`, and
`commit-manifest-index.py` after it in a sharded plan, run as subprocesses with the subject
`landed on <parent>`; or, with the parent checked out nowhere and the stamp in the tree holding
the phase branch, on that branch, with the parent fast-forwarded to it once more and the
ancestry read back. A stamp in a tree holding any other branch is left there and said
(`landingCommitSkipped`, not a failure), and so is one in a tree holding other pending changes to
the files the audit-state commit stages whole - a plan file differing from HEAD beyond this phase's
stamp fields, a journal row about anything else, any evidence change (`pending_beyond_stamp`), so
another session's work never rides into the landing's commit. A commit verb that refuses makes the
run exit 1. Under `review.perTask: phase` the merge is refused while a task recording a commit
lacks its answers, asked of the handed plan, of the worktree's copy on disk (`worktree_phase`) AND
of the branch tip's copy (`landed_answers_refusal`): from the parent's checkout the handed copy is
the plan as it stood at the fork, where no task records a commit yet, so it alone asks nothing.
Wherever a task's key reads `phase`, a tip whose copy records no sign-off verdict is refused - a
task's close reaches the branch only with the sign-off commit - and so is a tip whose copy cannot be
read when the plan is versioned (`plan_versioned`: inside the git root, not ignored, committed at
the parent or at `baseRef`); a plan git never commits is asked through its copy on disk, which must
then record the verdict. `ra10`-`ra15` hold it, and over a recorded verdict the refusal's remedy
names restoring the record or reporting it, never filing and signing off again, which both refuse
there (`ra16`, `ra17`). **Under every key**, the same verdict is asked
for when a filed phase return the landing can reach (`every_filed_return`: the evidence of every
worktree git lists, prunable ones skipped, the branch tip and the target branch's committed tree)
holds an answer only a human settles (`_filed_returns.needs_human`), or will not parse
(`unsettled_sentence`): only the sign-off verb writes the verdict, and it refuses while such an
answer is unsettled. `hl1`-`hl5` hold it. **A verdict covers what its sign-off read, wherever that
sits** (`read_set_refusal`): `audit-task.py signoff`, single or group, records in
`review.readReturns` the signature (`_filed_returns.return_signature`) of every filed phase return
it read - its checkout's evidence and the branch tip's committed returns, the tip's through the
same human stop - and the landing refuses a return needing a human whose signature is not in that
set unless a known checkout's driver settlement settles that answer. **A settlement binds the
answer it settled, not the return's name**: the driver's accept records each answer's key with the
signature of the return it sits in (`_filed_returns.settlement_after`, under
`answersAccepted.signatures`), and on this path a settlement counts only for a return carrying that
signature (`needs_human`'s `bound`) - another answer filed later under the name is not settled by
it, one under a name the verdict read (`read_names`) is refused whatever any record says, and a key
recorded with no signature settles nothing, the refusal naming it (`settled_by_name_only`; `rs8`-`rs10`,
`hs1`-`hs2b`). The sign-off verb and the landing read one set of records, every worktree git lists
and does not report prunable (`_filed_returns.settlement_checkouts`, `settlements`), so a sign-off from
the parent checkout honours a settlement made where the branch is checked out (`hs3`, `hs3b`).
Where a return sits no longer decides:
one filed after the verdict is refused in a sibling worktree, in the signing checkout after a
switch away and back, or brought to the tip by a merge of the target, and a copy of a read return
lands anywhere - the `rs` cases in `test_close_phase.py`, and `rr1`-`rr3b`, `gsp2` in
`test_audit_task.py` for the write. A verdict recording no read set, written by an earlier plugin,
keeps the reading by place (`_reach_refusal` routes it to `unseen_returns`, `verdict_reach_refusal`):
it settles only what its own checkout's sign-off read - a tip's verdict the returns the tip commits
and those of the checkout holding the branch, a return found only in the parent's evidence refused
whenever it was filed; an `evidence.dir` several checkouts share settled only by the signing
checkout's driver settlement; a plan stored outside the project (`VERDICT_AT_EITHER`) settling each
place through the record of the checkout holding it, and a return a ref commits through every
known checkout's. `landed_answers_refusal`'s docstring lists the placements that reading meets,
each with the `vr`, `hl` or `rs` case holding it by name, or the reason it cannot occur, or names it
unpinned; a verdict on the worktree's copy that the tip lacks is refused with the remedy of
committing it, since sign-off refuses again (`vr8`). A return any hand put where the sign-off read
it before the verdict is in the read set, the filing verb's or not. A
digest-moved refusal whose declared files hold uncommitted changes in the worktree holding the
branch names them (`uncommitted_declared`) and says to commit or revert them before recording,
since a run recorded over them is refused again (`cr19b`, `cr19c`). A re-run
over a landed phase - its branch gone or not - commits a stamp an earlier landing left as an
edit, and commits nothing when there is none. `lt` in `plugins/audit/tests/test_close_phase.py`
and `g17`/`g17b` in `tools/check-git-pipeline.py` hold it against real git. Each of the three plan writes here — the stamp, the
`mergedHead` backfill (`record_merged_head`) and the mirror — reads the plan and writes it while
holding the index lock every other plan writer takes (`under_index_lock`, through
`_panel_write.acquire_index_lock`). On the single-file layout, two closes or a close and a panel
save used to each write the copy they had read, and one write was lost while both answered ok.
A stamp or a backfill whose lock is not taken writes nothing; it says why and names the re-run of
close-phase that writes it. A stamp not written exits 1 with the cleanup held back. A backfill
not written prints `mergedHead NOT recorded` with that sentence. Every write is
revalidated, and a finding the write introduced restores the prior bytes through
`_panel_write.restore`'s temp file and replace (`_revalidated_write`), so the rollback is as
atomic as the write it undoes. Any failure of the mirror, the lock's own included, is a sentence
naming `audit-task.py settle`, never a failed merge. `test_close_phase.py` covers this with a
held lock and an inode check, plus two races between real processes: two closes released
together, and a close against a panel save with each in turn caught mid-write.

**It never runs `git switch`.** Not as a preference: `git switch <parent>` from inside the worktree
a phase ran in fails with `fatal: '<parent>' is already used by worktree at '<the main tree>'`, so
the sign-off the orchestrator documented was unavailable on exactly the runs `/audit:worktree`
recommends. Instead the merge happens **in the worktree that already holds the parent**, or — when
nothing holds it — as a no-checkout fast-forward. One path works from inside a worktree, from the
main tree and from a bare checkout.

**`meta.merge.auto: false` exits 0, not 1.** It is the human-in-the-loop switch: review, gates and
the sign-off commit all happen, then the run stops before the merge and prints the command it would
have run. A phase that is signed off and lands through a pull request is a real state, and the
plugin previously had no way to say it. Nothing is stamped on that path — a plan that records a
merge that did not happen is worse than one that records nothing.

**Two exit codes exist so callers can tell three failures apart.** `3` is *not a fast-forward* —
the parent moved while the phase ran, which is the normal case on a team repo and has a human
question attached. `4` is *could not be asked* — git absent, or refusing to describe the worktrees.
Folded into `1` they would be indistinguishable from "the tree was dirty", and a caller would retry
the wrong one.

**The verification is a second computation, not a re-reading of the first.** After the merge the
ancestry is re-asked with `merge-base --is-ancestor`; comparing the merge command's own output
against itself would be a check that cannot go red. Cleanup runs only after that answer is
`contained`, and stops at the first refusal — the steps are ordered because git enforces the order.

### `plugins/audit/scripts/git/manage-worktrees.py`
`list`, `add`, `remove`, `sweep` — the account of what `/audit:worktree` created, which the prose
composed as a path (`../<repo>-<phaseId>`) and then recorded nowhere. Git's own list is the
registry; the phase is joined onto it through `phase.branch`.

**The sweep refuses on two axes, and the second one is why.** A branch contained in its parent
means the *commits* are safe; it says nothing about the working tree. This project's own history
carries the worked example — a batch of worktrees whose branches were all merged and whose trees
still held unstaged edits, which is why retiring them cost six hundred lines of hand-written
evidence. So a worktree goes only when its branch is contained **and** its tree is clean, and
everything else is kept with the reason printed beside it.

**Read-only by default, and the verb is mandatory** — the grammar `/audit:logs prune` already uses.
`--apply` needs at least one of `--remove-worktrees` / `--delete-branches` / `--prune`; `--apply`
alone is a usage error, because "sweep everything" is not something this command infers. That
default is not timidity: `git worktree remove` destroys *ignored* files without complaint — a
`.env` or a `node_modules` that `git status` never mentioned — so the irreversible half needs an
explicit ask.

**Provenance decides what may be reaped, and it is not derivable from git.** `add` writes a marker
into the worktree's own admin directory — what `git rev-parse --git-dir` prints from inside it —
and the sweep touches only worktrees carrying it. The placement earns three properties: git
tolerates unknown files there, no manifest write is needed, and **the marker dies with its
subject**, so it can never outlive the worktree and authorise removing whatever next occupies the
path.

**`--include-strangers` was here and was removed, and the reason is worth keeping.** It widened the
sweep past the branches the plan names, judging the adopted worktrees against
`meta.developmentBranch` — a guess at a parent they never declared. It was added because the strict
sweep found nothing on this project's own repository: *every* linked worktree there was a stranger,
because parallel agent sessions and hand `git worktree add` calls do not go through the plan. That
was a real observation and the wrong conclusion. A worktree somebody opened by hand is
indistinguishable from ours by branch name and merge state, so a flag adopting on those two signals
deletes other people's working copies on the strength of a guess. `remove --path <dir>` is the
replacement: one directory, named by a human.

**And settlement is a separate question from containment.** A branch contained in its parent says
the commits are safe. `phase_settled` asks whether the plugin is *finished*: sign-off passed, no
task still open, `mergedAt` recorded — three marks, and the first missing one is the reason
reported. A phase can be merged early and still be running.

**Exit 5 means there was nothing to examine.** A sweep that looked at nothing and a sweep that
looked at everything and found it healthy are otherwise the same exit code and very nearly the same
sentence, and only one of them describes a repository somebody should feel good about.

### `plugins/audit/scripts/manifest/_commit_trail.py` + `repair-commits.py`
Is every recorded `task.commit` still reachable, and what to write when one is not. The manifest
names a SHA per finished task and derives `bug.fixedIn` from it; that is the audit trail, and it
is a trail only while git still reaches every commit it names. `clear()` nulls a lost task commit
and, with it, a bug's `fixedIn` holding that same commit — the copy `/audit:task done` stores,
which nothing else would ever move — and `changes_of()` is the journal's spelling of both.

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

### `plugins/audit/scripts/manifest/repair-tests-add.py`
The migration behind the `tests.add` shape rule. The schema asks for
`"<path>: <what it asserts>"` because that leading path is what `/audit:task add` and `scope`
carry into a task's `files` and the `fileIndex`, and `_invariants.commit_scope` grades a commit
against that list; an entry written as a sentence therefore leaves the case file outside the
scope the work is graded against. The validator says so on every unfinished `tdd` task and refuses
it — and **a refusal with no way through would strand every plan written before the rule**, which
is what this is: the migration this rule's own message points at.

**The only path it writes is one the entry already spells.** An entry that mentions
`tests/cart.spec.ts` in its prose is rewritten to open with it; an entry mentioning no path, or
more than one, is reported with the task that holds it and the command that repairs it by hand.
Nothing is derived from the task's `files`, from a naming convention or from the phase — a
sentence is visibly not a path, a wrong path is not, and the wrong one is worse to leave in the
field that grants commit scope. The bound on a **mention** is deliberately stricter than the
bound on a **declaration**: a token inside a sentence must carry a separator as well as a
filename, because ordinary prose is full of tokens that pass a filename test on their own.

**The rewrite only ever prepends**, so the entry comes back as the tail of its own replacement
and nothing its author wrote is lost — which is also why it is safe on a task already under way:
what `/audit:task scope`'s append-only rule protects is a grading that reads `files` backwards,
and a prefix can only add to the paths an entry names. `files` and the `fileIndex` are **not**
touched; they are `audit-task.py`'s to derive, and a second writer of that index is how two
writers come to disagree about it. Report mode is the default and writes nothing; `--apply` takes
the index lock, revalidates before saving, refuses rather than leave a half-repaired manifest, and
journals what moved. `tests_add_graded` in `_manifest_phases.py` is the filter both this and the
validator's warning read, so the migration cannot offer to repair an entry nothing complained
about.

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

**`usage_hint_violations()` holds the sister rule for argument parsing**: every
`ArgumentParser` built under `scripts/` is handed to `_claude_home.attach_usage_hint()` in
the scope that built it, before anything in that scope parses argv, so a usage error from an
older cached copy names this copy's version and any newer installed one. One call beside each
construction, never a copy of the hook. It reads calls, not text — a parser wrapped at
construction counts as hooked, and a `parents=` template counts as nothing to hook, because
it never parses argv itself — so a file that only names the constructor (`_refs.py` reading
other files' parsers, the hook's own docstring) is neither reported nor exempted.
`parser_sites()` is the full list it judges, hooked and bare alike. Sub-parsers built by
`add_subparsers()` are outside it: an unknown verb is the top parser's error, which the
hook already carries. Entry points that read `sys.argv` by hand build no parser and are
outside it too.

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
block alone catches a file that pastes the preamble once and then repeats only its
`import _output` / `install_path()` tail: it carries the TEXT once and bootstraps TWICE, so a
count of the whole block read the files under `panel/` doing exactly that as compliant
while the house rule said this function counted the preamble "once, never twice". It also
AST-checks that `install_path()` runs above the first sibling import — a preamble below
the imports it exists to enable is decoration. `_output.py` is exempt by name, for two
reasons: it *is* the marker, and it holds `PATH_PREAMBLE` as a string, so a text count over its own source
would read as compliant.

**`ui_surface_digests()` answers which files a surface's pictures are OF**, and it lives at
the anchor for the same reason the kept-files walk does: two readers at two layers, and a copy in
either would be the second implementation of "which files" this design exists to remove.
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
written into prose rots, because nothing compares it to the thing it describes — this recurred
more than once under the same shape, and every earlier response was to correct the figure, which
buys one green day. Three families of present-tense claim are recognised, and none was adopted before its
sites were counted and checked — an extension that fires on forty correct lines is worse than
no extension. What each measured on the day it landed: **cardinality** (`its N cases`) found
51 sites, 9 already wrong; **persistence** (`` `NAME` stayed at N ``) found 2, both already
wrong; **completeness** (`all N of them`, `all N … have`) found 4, 3 already
wrong. Re-derive any of them by breaking the check, never by reading this. All three take the same
remedy — **delete the number** — and the evidence for choosing that over "make it carry its
basis" is `CONTRIBUTING.md`, whose files-over-500 figure *does* name a command that prints it
and rotted in both halves anyway. A basis makes a claim checkable; only deleting the number
makes it un-rottable. Every property below is designed in and pinned by its own case: no
regex (this module carries `ast`, `os` and `sys` only, and hooks import it on every tool
call); history stays writable, so `stood at N` and `was still N` are legal and `stayed at N`
is not; a number carrying its own re-derivation is allowed, and the basis is read across a
line wrap because every document here is hard-wrapped; and the repair must itself read clean,
or the lint forbids its own remedy. The check also covers the number written as
a **word**, and `_numeral_span()` reads both spellings for every shape so there is no second
grammar to drift. Its table stops below `ten` on a measurement, not on taste — under `ten` a
written-out number in this tree is a determiner, a pronoun or an anaphor pointing at an
enumeration in the same breath, and the shapes cannot tell that from a count. What it cannot
see is written down with its direction — a count spelled as one of the small words that table
leaves out, claims split across a wrap, completeness with no auxiliary, persistence naming no
code in backticks, and a numeral written with an interior separator, which is a ratio or a
measurement and not a count of things — and every one of those is an **under**-count, which is
the quiet direction, so a clean result means "none of the known shapes", not "no claims".

**WHERE it looks is derived, and that was the other half of the same defect.** The
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
`layer_doc_drift()` closes the third leak in that seam: a module may open its docstring
with a layer, and now it has to be the layer `LAYERS` gives it. Two documents said `Layer 5` for
a module the table had already moved off, both were true when written, and nothing compared
either to the table — a stale ARGUMENT costs the next reader more than no argument does. Only a
module's claim about ITSELF is judged, anchored at the start of a docstring line, so one module
correctly citing another's layer in running prose is left alone; the allow row in
`tools/prove-gates.py` is what holds that line, because a pattern widened to catch the prose
convicts dozens of accurate sentences.
`doc_prose_numbers()` runs `_output`'s prose-number rule over every `.md` this repo keeps — the
derived set described under `_output.py` above, product documents included — and it **delegates**
to `_output._prose_number_claim` rather than restating the shapes, because a second copy of the
pattern would be precisely the defect both scanners exist to catch; a case asserts there is no
second definition. `_PROSE_DOCS` survives as the three documents that were once the whole list,
and it is now a BLINDNESS check: each claims to be a definition of how this repo works, so a
derivation that stopped reaching one has gone quiet rather than clean — which is the direction a
floor derived from the walk itself cannot see. `navigability_violations()` and `ui_navigability_violations()` both **name** an
asset they could not read and a directory they could not list, rather than skipping it: the
`.py` side had already reported a file it could not *tokenize* while quietly swallowing one it
could not *open*, and the `ui/` side returned an empty list for a missing `scripts/ui/` — the whole
report and panel UI gone, printing exactly what a clean tree prints. `--selftest`.
`state_write_violations()` holds the rule that a state file is replaced only through a sanctioned
writer: every `os.replace`/`os.rename` under `scripts/` and `hooks/` — through `os.`, a module
alias, or a name imported from `os` — must sit in a function `STATE_WRITERS` names, and each row
carries a reason and must still name a live site, so the table cannot excuse code nobody wrote.
The writers a new site routes through are `_manifest_io.atomic_write_text` (which
`atomic_write_json` writes through) and, on the hooks side, `_config.atomic_write_text`; both take
a temp name of their own, which is what a fixed `<target>.tmp` shared between two writers running
at once did not. `state_write_sites()` prints the corpus the rule judged. A method of the same name
on a string or a path is not the `os` module's and is not read — the allow row in
`tools/prove-gates.py` holds that line.

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
place to declare away the defect the rule exists to find. Until this was written down, the
convention existed only as a lint failure: an hour every new author pays once, and it had been
paid before it was documented.

`artifact_version_drift()` asks the same question of a COMMITTED PAGE rather than of
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

`screenshot_capture_drift()` asks it of a PICTURE, which is why it cannot be answered the
same way. The panel paints its own version in the topbar and every shot starts at the top of the
page, so each committed PNG under `docs/screenshots/` claims a build — and reading that claim
back means reading text out of an image. `tools/capture-screenshots.mjs` refuses to compare
these pixels at all — its header declines three repairs by name, including
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
scope on purpose — it is a VHS recording of a real Claude Code session (`tools/demo-gate.tape`,
driven by `tools/capture-demo-gif.py --record`), not a picture of a surface this tree
assembles. Its record lives in the same sidecar under its own `gifs` key: the GIF's sha256,
the CLI version and model it was recorded with, the out-of-plan edit Claude sent, and the
plan gate's refusal as the session showed it. It is graded by that tool's `--check`, which
replays the recorded edit against `require-plan.py` without a session and fails when the
refusal or the bytes moved, not by this rule.

**That version answered only half the question, and the source digest below is the other half.**
"Was this captured at this release" is not "does this picture still show the current UI", and
the difference was
live: commits landed under `scripts/ui/` after the last re-capture, the recorded version was
still current, and this rule was green over pictures of a panel that had since moved. Pixels
cannot close it, but the UI's **sources** are committed bytes, so a digest
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

`handbook_drift()` asks it of the one published page with **no generator behind it**.
`docs/handbook.html` is served by GitHub Pages beside the live demo and nothing read it: the
rendered reports are compared byte for byte, `docs/index.html` is proven a byte copy, every
screenshot records the version it was shot at, and the handbook walked past
`artifact_version_drift()` carrying no stamp to compare — correctly, and saying nothing. So it
could assert something the code had stopped doing and stay green for ever, and it had: before it
was rewritten it described none of the test-evidence feature, its masthead and its footer named
two different and both-stale versions, and it described a command as interactive when every
answer is a flag.

**Deliberately not a byte comparison**, which is the decision rather than a shortcut: a byte
check needs a generator to compare against, and writing one to hold a hand-written page is a
bigger commitment than the gap deserves. What is checkable without one is the page's
**structural** claims, and the page makes them out loud — "every command, flag and default here
is the same wherever it is installed". Four arms, each reporting the size of what it examined
beside its findings: a verb that has a command file, an option spelling the product still
carries, a dotted path written from the root of a document this plugin publishes that a schema
still declares, and an internal link that lands on an `id`. The counts are not decoration —
every arm narrows a long page down to a small set, and a narrowing that reaches zero produces
the same empty finding list as a page that is entirely correct.

**The region it reads is the text a reader reads**, and that narrowing is the whole reason the
rule is quiet enough to keep. A CSS custom property is spelled exactly like a command-line
option, so a reader over the whole file would report this page's own design tokens as options
the plugin does not accept; the stylesheet, the inline diagrams and the inline scripts are
dropped whole, then the tags, then the entities are resolved. The repair for that class is the
narrowing and never a looser needle — a pattern widened until the tokens passed would stop
catching an option that was really removed. The one place a page may name something the product
does not carry is `HANDBOOK_ABSENT_VERBS` / `HANDBOOK_FOREIGN_OPTIONS`, each row carrying a
reason and checked in **both** directions: a row for a verb that has since been built, or for
something the page no longer names, is reported exactly as a violation is.

`manifest_placeholder_drift()` asks whether a command file still hands a script the
`<manifestPath>` placeholder after that script learned to find the manifest itself.
`self_resolving_scripts()` reads the AST of every `.py` under `plugins/audit/scripts/` for a CALL
to `<module>.resolve_manifest(...)` — not the string or the docstring naming it, which this file
and `_manifest_io.py` both carry — and returns the basenames that make the call. The drift check
then walks `commands/*.md` for a line handing one of those scripts the placeholder right after its
name and reports it: the command still types the path for a script that would find it alone.
`MANIFEST_PLACEHOLDER_PENDING` is where a command file still handing the placeholder on would be
excused, each row carrying the reason; it is empty since the pipeline commands stopped reading the
orchestration reference, and a row whose document no longer carries that line is itself a
finding, so an excuse cannot go stale quietly either.

`followed_anchor_drift()` holds the README's followed table to the two places the model meets a
followed rule once no pipeline command reads reference prose: each row's "Stated in" must name a
step of `drive-phase.py`'s `STEPS` whose `rule` is not empty - read off that literal by AST, a
module-level string the table names read as that string - or a bullet of an agent prompt opening
with the bolded lead the row names. A row still citing a reference section (a `§`), a step the
driver lacks or prints no rule at, a lead no bullet opens with, a row naming neither, and a README
with no table or no row are each a problem; `rows` and `anchors` are counted beside them. It cannot
see whether the printed rule says what the row says - that is the reviewer's, as for every prose
rule. The `fa` cases in `tests/test__refs.py` hold each refusal beside the allow case.

`--selftest`.

### `plugins/audit/scripts/usage/_usage_core.py`
The arithmetic the whole metering stack stands on, and nothing else: the `DEFAULT_PRICING`
table plus `rates_for`/`price`, one ISO parser and one hour-bucket rule, the roll-ups
(`totals`, `aggregate`, `aggregate_area`, `rows_for_area`, `heatmap`) the CLI, the report and
the panel all read, `priced_at_read` which prices the rows those roll-ups sum at the resolved
table and counts the ones it cannot, and the three readers every analytics pass starts from (`task_index`,
`_tokens`, `_cost`) — here because the four analytics modules sit at one layer and may not
import a peer. Values in, values out — no file, no process, no transcript — which is why its
cases need no fixture directory. `pricing_divergences()` lives here too: `hooks/_config.py`
must price a model with no config present and may import nothing from `scripts/`, so its copy
of the rate table is deliberate and the `pp` cases are what keep the two identical. The
table's as-of date and source URL are mirrored the same way (`PRICING_AS_OF`,
`PRICING_SOURCE_URL`), and `pricing_provenance_divergences()` with the `pv6` case holds them
equal.
`--selftest`.

### `plugins/audit/scripts/usage/_usage_spend.py`, `_usage_economics.py`, `_usage_routing.py`, `_usage_coverage.py`
What the ledger MEANS, as `rows -> dict` functions. One file until v0.40.x, when it reached 955
lines and was cut on its own section markers — every body moved by line range, so each
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
  the page so `panel.js` cannot restate it differently. Since P56.6, also `gate_scope_comparison`,
  `gate_reuse_comparison`, `sibling_spend_comparison` and the `plan_cost_claim` that folds them
  — the plan's own cost against the same work without one, as three named comparisons that each
  answer or refuse (`CANNOT_COMPARE`) rather than a single ratio nothing could check.
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
`append(project, entry) -> path|False`, `verify`, the divergence half behind
`audit-journal.py merge` (`merge_rows`/`merge_text`/`write_merged`, and `anchor_verdict`
behind `verify`'s git anchor), `session_index` behind `sessions`, and the row/hash
vocabulary underneath them. It sits at the bottom because two modules that are not commands
need it — `_help` (layer 3) normalises one row to show a reader what a row looks like,
`audit-doctor` reads
and verifies — and because `hooks/_config.py` asks it for `journal_dir` on every tool call,
where executing an argument parser and four subcommand bodies to resolve one path is cost
with no caller. Three of those reaches were `_loader` loads of `audit-journal.py`; the
fourth, `_panel_state`'s, was the edge `_deps` deliberately could not see (it spelled
`script_path()` on one line and `load()` on the next) and is now an ordinary import.

**A row's actor answers "which agent", and absence there is a reading rather than a gap.**
`actor.agent` carries the writer inside a session — a subagent's id, or the word the hooks
spell the orchestrator with — because the `sessionId` beside it is shared by both and could
never separate them. `agent_token()` sanitises and bounds it the way `env_session_id()` does
its own field: an agent id is opaque and names neither a machine nor a person, so the
question here is length and path safety, not redaction. A writer that named no agent gets no
field, and this module never substitutes one: the panel and the CLI are not agents, and a
default would write the orchestrator's name onto a row it did not write. `actor.via` is what
tells that reading apart from a row written before the field existed. The field changes a
row's bytes and the hash covers whatever fields are present, so both generations chain and
verify in one file — `ag6`/`ag7` in `test__journal_io.py` drive exactly that file.

**Two writes, with deliberately opposite failure contracts, and a reader who assumes one
rule for both will get it wrong.** `append(project, entry)` returns the path the row landed
in, or `False`, and NEVER raises: it records a write that has already succeeded, and such a
write must not be reported as failed because the record of it could not be written. (The
path rather than `True` is because the `journal-writes` hook puts it in a per-session sidecar
so `guard-bash-writes` can tell the plugin's own append from a shell write into the trail;
every caller that boolean-tests the result is unchanged, because a non-empty path is
truthy.) `write_merged(path, text)` **raises** on anything that stopped it, because it is not
a record of a write — it IS the write, and a caller told it was fine would go on to commit a
conflicted file. It also takes the same lock an append takes, and that is not optional here:
an append reads the file's tail to learn its `prev` while a merge REPLACES that tail, so
without the lock an append that had already read the old tail would land a row chained to a
row the merge had just replaced — a break that reads exactly like a deleted row, which is the
false tamper verdict the lock exists to prevent. It goes through a temporary file in the same
directory, so an interrupted merge leaves either the old file or the new one and never half
of each, and a half-written temporary is removed without swallowing the exception that
stopped it.

### `plugins/audit/scripts/governance/audit-journal.py`
The CLI over `_journal_io`: `append | verify | show | archive | merge | sessions`, turning
the library's dicts into printed lines and an exit code (0 healthy, warnings allowed;
1 findings — the chain does not hold, or a merge refused; 2 usage).

**`verify` reads BOTH chained records; every other subcommand is the journal's alone.** Since
the evidence ledger was given this chain there are two committed append-only files beside a
manifest, and they differ in what they are for rather than in how they are protected — so one
command asks them one question. Each prints its own labelled verdict (`OK (journal)` /
`OK (evidence)`, `BROKEN (<record>)`), neither can hide the other's, and the exit code is
non-zero when either has findings. `--json` returns `{ok, journal, evidence}`: the old flat
keys are *gone* rather than kept beside the new ones, because a reader still taking a
top-level `findings` would be reading the journal's alone and calling it the verdict.

One file per writer per month (`<journal dir>/<YYYY-MM>.<writerId>.jsonl`, default beside the
manifest) so parallel worktrees never conflict; each row carries `{v, ts, actor, action,
target, summary, stateHash, prev, hash}`, sha256 over canonical JSON, with the first row's
`prev` derived from the file's own base name so a file cannot be renamed into another
writer's slot. **Tamper-evident, not tamper-proof** —
stated in the module, the README, the panel's own Settings card and SECURITY.md, because a
forger who rewrites the whole file still verifies. `--selftest`.

**What `verify` grades as what.** FINDINGS are breaks: a row that does not hash to its own
contents (edited after it was written), a row that does not follow the one before it
(deleted, reordered, or the file renamed), a corrupted line that is not the last line, and a
committed row that is no longer in the working copy with its content intact. WARNINGS are
the honest maybes: a torn tail (a crash, not a cover-up), out-of-band drift — the document
moved with no row to say why, which is normal for anything the plugin did not write — the
same basename existing both live and archived (both chains verify off the same genesis seed,
so its rows double-count), and a file whose LINKS were recomputed while every committed
row's content survived.

**That last warning class is new with `merge`, and it is why the git anchor asks about ROWS
and not about bytes.** "The committed copy is a byte prefix of the working copy" stood
in for append-only-across-commits, which is a good proxy for as long as appending is the only
thing that ever happens to the file. Resolving a divergence re-links every row after the
divergence point, so the bytes after it are new while no row's CONTENT moved at all — and
neither side of a divergence satisfies the prefix either, so `verify` reported every sound
resolution as broken and could tell nobody whether their resolution was sound. Presence,
content and order are what the proxy was reaching for and they are checkable directly:
`_journal_io.anchor_verdict` holds that property, states what it stopped being able to forbid
(a row may now be INSERTED between committed rows, which is exactly what a merge does with
the other side's tail — reported as a warning rather than passing in silence), and the byte
prefix is still tried first and still settles almost every file. **What that warning cannot
do is name its own cause**: a legitimate re-link and a fabricated row spliced in among
committed rows and re-chained produce the identical verdict, and neither the merge commit nor
the `journal.merge` marker row is required for the benign reading — so no check consults
either, and the warning's job is to send a human to read the extra rows. `_doctor_trail`'s
`journal_warning_advice` is where that is worded for an operator.

**`merge` is the verb a journal conflict needs and did not have** (and an evidence ledger's, since it is chained the same way). One writer on two
BRANCHES is ordinary while a phase is paused, and the per-writer file split does not separate
them — so a landing phase produces one file with a shared prefix and two tails, which cannot
be resolved by editing, because each divergent row's hash covers a `prev` only its own side
has. With no verb the resolution keeps one tail and loses the other in a second parent nobody
reads again. It re-chains the UNION of the two sides, recomputing `prev` and `hash` and
touching no row's content, and it defaults to the two sides git already has (index stages 2
and 3 of `--file`), so during a conflict it needs nothing but the path. That default is also
half of what leaves a re-chained file AUDITABLE rather than merely rewritten — both inputs stay
in git and the merge commit holds both parents, so a reviewer can read either side — and the
command says so only of the sides that really came from the index, because it is a claim it
cannot support about two files a caller extracted itself. What it does not buy is a check:
nothing in this tree requires that commit to exist before it will read a re-linked chain as
benign, which is why `verify`'s warning for one is a pointer at a human rather than a
verdict. It is deliberately not blocked by `journal.enabled: false`: that switch
governs whether new news is RECORDED, while this repairs a file that already exists and is
already in conflict, and refusing would leave the operator holding a conflicted file with no
verb that admits to it. What it refuses rather than guesses is `_journal_io.merge_rows`'
answer and is documented there — the refusal set is the library's contract and this is a
front end over it.

**`sessions` answers the question a file NAME cannot.** The name carries the writer id
the ROW supplied, clipped to fit a name, and the hook that writes most rows is handed a
different id from the one a session reads from Bash — so the mapping lives in the rows, and
this prints it per file with the `actor.sessionId` and `actor.envSessionId` values behind it,
marking the file this session wrote. A file with no `envSessionId` on any row is reported as
meaning either that the writer read the same id from its environment or that the rows predate
the field, never as the reassuring one of those.

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

**The fixture is a real git repository**, because `full_status` answers whole only when git says
a full run's head contains a phase's `mergedHead`, and a directory with no repository can only
answer unknown. `write_history()` writes it into `<out-dir>/.git` as loose objects the generator
builds itself — no git process runs, so no hook, identity, template or `GIT_*` variable of the
caller's reaches a commit, and every date comes from the plan, so the commit names are the same
on every machine. The real objects are the merges `generate()` stamps as each phase's
`mergedHead` and the commit the one recorded full run measured, which sits right after the
first of those merges: that phase reads whole, every later one provisional, and the earliest
done phase, which records no `mergedHead`, unknown. Every task's `commit` and every phase's
`baseRef` stays a stable fake no object backs, so a reader asking git about those — the
doctor's commit trail, for one — calls them dangling here, which is a property of the fixture
and not a finding. **It never writes into a repository it did not make:** `history_refusal()` is
asked before the manifest, the ledger or a single object is written, and accepts an existing
`.git` only when it is a directory whose `HEAD`, `config` and branch ref are byte for byte what
this history would write. Anything else — a linked worktree's `.git` file, a link, somebody's
repository — and `gen-demo-manifest.py` exits 2 with the reason, having written nothing.

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
one entry point loading another for one name, and the last edge
`KNOWN_LAYER_DEBT` then carried. The alternative to a small module was not a bigger one; it was a
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
and `migrate-manifest` all used to load `validate-manifest.py` through `_loader`, four of the
edges `KNOWN_LAYER_DEBT` then carried.

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

**`_check_muted` grades `meta.muted`.** A mute naming no bug, or a bug `bugs[]` does not hold, is a
finding. A mute whose bug is closed by its effective status (`_closed_bugs`: the bug's
`_manifest_io.effective_bug_status` in `_status_facts.CLOSED_BUG`, the reading
`run-test-gate.withheld_mutes` refuses the mute by) is a WARNING, `rules.muted.bug-closed`,
carrying `audit-task.py unmute --test <path>` — a warning for the expiry's reason: the runner
already stops honouring it, and a finding would freeze the very verb that lifts it.

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

### `plugins/audit/scripts/manifest/_filed_returns.py`
Where an agent's **filed return** lives, what shape it must have, and how it is read
(layer 1). `audit-task.py file-return` writes a return, `audit-task.py done` and
`audit-lookup.py brief` read it, and `commit-task-work.py` reads its `claims` — three entry
points at one layer that may not import each other, so the facts they must agree on live
here once. `return_rel`/`return_path` derive `<evidence dir>/returns/<taskId>/<start>.<role>.json`
from the task's current `startedAt`, so a re-start files beside the earlier attempt's return
and an earlier start's return is never read as this one's; `return_problems` names every field
a return falls short on against the shape its role's agent definition declares (the
executor's red-first words are `RED_FIRST_WORDS`, held equal to the schema enum by `fr7`);
`file_once` is the exclusive create that refuses a second filing and leaves the first
byte-identical; `read_filed_return` reports a file that will not parse as a problem, never as
an absence; `claims_from_return` hands the commit path the `claims` text verbatim. The evidence
directory is handed in rather than resolved — resolving it is `_evidence_io`'s, one layer up —
so the module reaches nothing but `_output`. `needs_human` is the one reading of which phase-return
answers only a human settles - a task entry's `diverges`/`cannot-tell`, `not-proved` or `flagged`,
and a phase intent of `diverges`/`cannot-tell` - shared by the driver's triage and
`audit-task.py signoff`, which refuses while one is unsettled; `settlement_record` reads the
settlement the triage's `--answer accept` writes at `drive_state_path` (`<stateDir>/drive/<phase>.json`)
through `settlement_after` - each settled answer's key, and beside it the signature of the return
it sits in, the content the settlement binds - `settled_answers` its keys alone for the reading by
place, and a record that will not parse is a problem, never nothing settled (`hn4`-`hn12`). `drive_state` reads that file
whole and `review_marked` says whether it marks a phase review at a head - without one, and where
a review skill resolves or a task is owed its answers, the driver's next sign-off pass reads a phase
return already filed at the current head, and dispatches the review only where none is, which the
verb's remedy says with that condition (`hd29q`, `hd29r`); `return_body`
is the one parse of a return's text, shared by the read off disk and `close-phase.py`'s read of
the branch tip. What a verdict read lives here too, because sign-off writes it and the landing
compares against it: `return_signature` is the sha256 of a return's name, body and parse problem -
never where it sits - `read_record` the `review.readReturns` rows a sign-off writes, `read_set`
their signatures or None for a verdict recording none, and `ref_phase_returns` /
`tip_phase_returns` read the returns a branch commits straight off git, the one command this
module runs (`rd1`-`rd4`). What it cannot hold: the task
id and role a caller files under are the caller's word. Cases in `plugins/audit/tests/test__filed_returns.py`.

### `plugins/audit/scripts/manifest/_task_outputs.py`
What a task's **`outputs`** pattern may be, and what an honoured one reaches (layer 1).
`files` names what a task *edits* and is enumerated, so every entry can owe a `fileIndex`
row; `outputs` names what a run *produces* — the documents it writes, the evidence rows it
appends — which cannot be enumerated before the run makes them. So it is patterns, and a
pattern is the only thing on a task that can **widen** what the plan gate allows.

**The bound is the whole feature.** `output_pattern_problem` refuses, by name, any entry
whose **first segment is not a literal directory name**: `**`, `.`, `*/x`, an absolute path,
a `~` path and anything carrying a `..` segment. Everything *under* the anchored name may be
a pattern — that is the point of the key — but the head is the segment that decides how much
of the repository the entry reaches, and an entry reaching all of it is the plan gate
switched off by a plan. `output_covers` is the matcher, segment-aware so `docs/*` is the
directory's own entries and `docs/**` is everything under it (`fnmatch` over the whole string
would let one star cross a separator and hand a reader a wider scope than they declared);
`output_problems` grades a list for a writer, and `honoured` is the **only** way to a list a
reader may act on.

**Three readers in two trees that cannot import each other**: `audit-task.py` before a write,
`_manifest_phases._walk_phases` over an entry already written, and the plan gate under
`hooks/`, which loads this file by path. Both halves live here together — two modules holding
one half each is how a pattern comes to be refused by the writer and matched by the reader.
When the hook cannot load it, it honours **no** pattern at all: an unreadable rule must make
the gate louder, never wider.

**It is not in `_manifest_vocab.py`, and that is a cost decision.** It started there. That
module's `SCHEMA_ANCHORS` comment declines to derive its enums from the schema partly because
nothing on the per-tool-call hook path loads it — a premise `mv37` walks the real import graph
to hold — and a rule the plan gate must ask spent that premise for an unrelated reason. It
sits at layer 1 for `_locks`' argument word for word: the smaller the module a hook resolves
by path on every tool call, the better.

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

**The read side is part of the rule.** `list` was the one verb no
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

**`list` prints its table here**, for the same reason the other three verbs live behind a
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
naming a source path is the shape `guard-secrets-read` refuses, so the check would
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

**`--item` and `--fetched` are two shapes and two questions**, which is why they are
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

**A `NOTE:` line travels beside the verdict and moves neither half of it.**
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

**The rank has a source and the name had none.** `levels_from_backlog_config()` takes the
bug rung's rank off `bugsBehavior` and its NAME off `bug_type(ado)`, i.e. `meta.ado.types.bug` —
the same derivation `inventory()` stamps a bug row with, so the ladder key and the row graded
against it cannot be two spellings. A literal there filed the rank under a name no work item
carries on a board that renamed the type, and every bug on the most governed kind of board came
back `not verified`. `resolve-ado-parent.py --hierarchy-from` is the door that reaches it: the
function had no caller at all while three documents carried the rule instead.

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
three when the name stopped being a literal. The mode prints the block whole, `fetchedAt`
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
cycles, `fileIndex` integrity in **both** directions, the reciprocal `bug ↔ task` link,
parked `proposals[]` (reserved ids, staged refs, the `materializedAs`/status pair), and a
stored phase or bug value its derivation answers differently (`_check_derived`, one warning
per record in the `<kind> <id>: <body>` shape with an id-free body naming `SETTLE_COMMAND`, so
`_warning_groups.collapse` prints a stale plan as a count per kind of move). Each takes the index `_manifest_phases` produced, the manifest,
or both, and returns its own `(findings, warnings)` — no accumulator shared, no order depended
on, so a case can call any of them with a hand-built argument and no file anywhere near it.

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
Two warnings are asked here rather than by `validate()`, because the assembled manifest has
already lost what they are about: an index-only field in a shard body
(`_manifest_io.index_only_in_bodies`) and an index stub whose mirrored key has fallen behind
its shard (`_manifest_io.stale_stubs`). The second, like `_manifest_crossrefs._check_derived`'s
stored-against-derived warning, names `audit-task.py settle` - a warning and never a finding,
because every plan written before the verbs stored derived values carries some.

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
(the gate verdict) each used to load `audit-status.py` for it, three of the edges
`KNOWN_LAYER_DEBT` then carried. `usage_summary` and `discovery_block` do read the world, so they
stayed with the command. `live_view`, `row_copies` and `ready_counts` are the pure half of
reading a phase in flight elsewhere: `_live_copy` reads the copies, and these lay them over the
plan and name each row's copy, the same way for every surface that shows one.

### `plugins/audit/scripts/status/_live_copy.py`
Which copy holds a phase in flight live (layer 6): a phase run under a lock, or worked on in
a linked worktree whose branch is not merged here, is read from that worktree's file -
uncommitted edits included - or from its branch's committed copy, and each read names the
copy it came from. `/audit:status`, the panel and the rendered report all show such a phase,
so the reader (`in_flight`, `flight_for`, `live_reads`) lives here and nowhere else, and
`_status_facts.live_view` is its pure half: it lays the reads over the plan and returns the
copy note for each row. At layer 6 because it asks git through `_scoped_commit` (layer 5);
`audit-status`, `render-report` and `panel-server` import it, and `_panel_state` (layer 5)
takes it as `build_state(live=...)` from the server. What certifies stays on this checkout's
own plan on every surface: the gate, the bug counts and the bug table.

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
. Its `<manifest>` positional is optional, resolved the same way as every other first-contact
command: `_manifest_io.resolve_manifest` against the argument, else the config's `manifestPath`,
else `docs/audit/audit-plan.json`.

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

**`plugin_integrity` asks a marketplace-cache install too.** A copy Claude Code installed into
its plugin cache is a plain directory, not a clone, so the checkout question has no answer
there — and the row used to warn on every such install that nothing recorded what it should
contain. Something does: `installed_plugins.json` records the `gitCommitSha` the copy was made
from and `known_marketplaces.json` names the marketplace clone that holds it (both read through
`_claude_home`, fail-open, and the row says they are undocumented). `cache_integrity` compares
every file `git archive` of that commit publishes under the plugin's directory with the cache
copy, byte for byte, and names each file that differs or is missing. A file the cache holds and
the commit does not publish is not compared - there is nothing to compare it with - and it is not
harmless: `__pycache__/*.pyc` beside a published `.py` is what Python executes when its recorded
source size and mtime match. So every such file under `hooks/` and `scripts/` is named in the row
as an extra, beside a verdict that stays about the published files. Bytecode is counted instead
of named only when BOTH halves check out: its header records the published source's size and
mtime - the condition under which Python runs it - and its body matches a fresh compile of that
source by this interpreter, under the file name the body records (a hook reaches `scripts/` by
`hooks/../scripts/`). A matching header alone says nothing about the body: a restore inside one
second at one size leaves exactly that. Another interpreter's bytecode with a matching header is
counted apart, as not body-verified. Unverifiable only when a side
is missing.

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
The checks that compare a declaration against the world it claims to describe — count them
with `grep -c '^def check_' plugins/audit/scripts/status/_doctor_policy.py`, because this
sentence has carried a stale figure before: `meta.areas` roots against the tree and phase
tags against the registry (v0.28), the capability policy against the plan it governs and
against this machine's inventory (v0.30, dead patterns v0.38), `meta.buildCommands` runners
against PATH, the branch-naming convention, and the skills the plan names — first against
this machine and then, as a second half, against what a CLONE would load. Every row
is a WARNING at most — a missing directory or an uninstalled runner is a gap in this
checkout or this machine, never proof the repo is broken, which is the lesson CI's manifest
job taught by failing over a correct observation. `_leading_executable` resolves what a
command would actually run (`cd x &&`, `env`, `VAR=v` prefixes) and returns None rather than
guessing at shell control flow. `portability_mode` reads the tier the second half grades at,
falling back to the hooks' own `DEFAULTS` rather than to a literal. The layer is in
`_deps.LAYERS` and is deliberately not restated here: two docstrings claimed a layer this
file had already left, and nothing compared either of them to the table.

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
journal's own `verify` rather than re-deriving the verdict — a diagnostic with its own
opinion about whether a chain is intact is a second implementation that can disagree with the
one that matters — and grades a BROKEN chain a FINDING, because a row that was edited, deleted
or reordered is not something that happens by accident. A journal file **git tracks that is
not in the working tree** is the other FINDING, and it reaches the doctor even when the whole
directory is gone: `verify` asks git what the index holds under that path before it gives up
on a walk that has nothing to walk, so a removed trail is reported as a removed trail rather
than as a project that has never recorded anything. Everything else is a WARNING at most,
and the warnings are not one thing: a torn tail is an interrupted writer, out-of-band drift is
a recorded document moving with no row to explain it, and a **RE-LINKED** chain is a file whose
committed rows all survived while the bytes after one of them are new.

**That third class is the one to read carefully, because this check cannot tell what caused
it.** `audit-journal.py merge` re-links a chain to resolve a divergence — and splicing a
fabricated row in among rows that are already committed re-links it identically. Same warning,
and nothing here separates them. Neither a merge commit nor a `journal.merge` marker row is
REQUIRED for the harmless reading, so nothing mechanically confirms it: what the warning buys
is that the operator is sent to look, at the extra rows (`audit-journal.py show`) and at the
merge they already know about (`git log --merges`) — a pointer, never a verdict.
`journal_warning_advice` is why that is said per class: one repair line for each class actually
present and none about a class that is not (an earlier unconditional sentence about out-of-band
drift sent an operator hunting a git checkout that was never there, and an operator who finds
nothing learns to read the row as noise), and a warning it does not recognise gets a pointer
instead of a guessed cause.

`_journal_never_committed` rides `audit-journal`'s porcelain seam for the 7-day
uncommitted-file warning, keyed by journal-relative path so a live and an archived month
cannot read as one another. Layer 4, set by the `usage_ledger` load.

`check_running_plugin` answers the question beside it — **which copy of the plugin ran
them.** `CLAUDE_PLUGIN_ROOT` is fixed when a session starts, so a session that began
before an upgrade keeps executing the copy it started with, and the harness substitutes that
variable into a command string rather than exporting it — so this command runs with nothing
in its environment naming the hooks' root. Disk is the whole channel and there are two things
on it: the STAMP `detect-plan-skip` writes on every prompt (`_config.running_plugin_stamps`),
which can establish agreement, and the SHAPE of a `guard-bash-writes` slot
(`bash_state_shape` off that hook's own `default_state()`, then `state_shape_drift`), which
can only refute it — and is the arm that works against a copy too old to have ever stamped
anything, which is the evidence the original incident was diagnosed by. `running_plugin_verdict`
folds them into three outcomes: they agree, they differ, or it was NOT ESTABLISHED — and the
third is not the first, so it warns rather than reading as clean. Every branch is OK or
WARNING; a stale plugin is a thing to tell somebody, not a thing to fail a run on.

**It grades each copy's own age against a stated idle bound, never against the session
asking.** A session that has ended leaves its stamp, and state GC keeps it for days, so counting
every stamp that is not this copy as drift held the row yellow on one dead session's file. The
first repair graded copies against the newest stamp, and that was wrong: the session asking for
the row has always just prompted, so every other session - one mid-turn on an older copy
included - looked superseded. So the stamp's mtime now means the last GUARDED TOOL CALL:
`guard-secrets-read` (Read, Grep, Bash and MCP calls) refreshes it through
`_config.refresh_running_stamp`, throttled to one write per `RUNNING_STAMP_REFRESH_SECONDS`, and a
call inside the throttle pays one `stat`. `split_history` then files a copy other than this one
as HISTORY only when its newest stamp is older than `IDLE_BOUND_SECONDS`, and the row prints the
bound with its number; a foreign copy inside it is live, a WARNING that says when it was last
active and that it may still be running. The limit is stated rather than hidden: a tool outside
`guard-secrets-read`'s `hooks.json` matcher, `Read|Grep|Bash|mcp__.*`, refreshes nothing, so a
session using only such tools, or waiting on its user, for longer than the bound reads as history
until its next prompt or matched call. History is worded as what the
bound can know - no guarded tool call within it, so ENDED, OR IDLE WAITING ON ITS USER - and the
refresh runs after the guard's verdict, through `_config.refresh_session_stamp`, which computes
the state directory inside its own never-raise: a guard's `main` exits 0 on an exception, and a
refresh that raised before the decision once turned a blocked secret read into an allowed one.

**`check_task_restarts`/`check_gate_patterns` answer what KEEPS HAPPENING, not only what is
true now** — a task started more times than any other (`task.start` rows grouped by
`details.taskId`), and a gate that has run repeatedly and never once failed (the same
`_evidence_io.gate_tally` a plan proposal folds into a claim in `propose-gates.py`). Both hold
the same floor: ONE OCCURRENCE IS NOT A PATTERN, so a trail thinner than
`RESTART_FLOOR`/`_evidence_io.MIN_HISTORY_RUNS` prints NOT ESTABLISHED rather than a clean OK
or a finding it cannot support, and both grade a real pattern a WARNING, never a FINDING — a
state cannot tell an operator they are paying for a gate that keeps earning nothing; only the
trail can, and doing so is advice rather than a build failure.

**`check_couplings` ages a coupling in green measured full runs, never in days, and never by a
run that muted it.** `_measured_run_moments` keeps `(moment, mutedTests)` for every green
measured full run — `_evidence_io._measurement_disqualification`, so a run with no tested head
still counts — with each moment read by `_evidence_io.stamp_moment`, the ledger's own ordering
read. `_muted_tests` gathers every test a mute excused in the row, from the row's `muted` list and
every step's, in `_norm`'s spelling. `coupling_age` counts the runs after the entry's
`lastCaught` (else its `learnedAt`) whose `mutedTests` do not hold the entry's test: a row that
reads green because the mute hid that test's failure is not a pass of it, and counting it would
read "failed every run" as "caught nothing". An entry that cannot be aged gets `_relearn_fix`'s
`uncouple` then `couple` pair, which spells `--basis-run` and `--basis-head`, the flags `couple`
refuses to learn without, so the remedy is not refused the moment it is typed, and `--phases`
for the phases that run covered, which `couple` accepts but does not require.

### `plugins/audit/scripts/status/_doctor_completions.py`
The one check that CORRELATES two records rather than inspecting one: the journal's close
receipts against the manifest's done tasks, the commit SHAs those tasks name against what git
has, and the usage ledger's coverage of the same ids. A receipt is a row carrying the task's
current `completedAt`: the hook-emitted `task.complete`, or the `done` verb's own `task.done` —
the only record of a close the hook did not watch, such as one run in a linked worktree. A
`task.complete` carrying no `completedAt` still receipts its task id alone. A done task inside the record era with neither is positive evidence the manifest was
edited outside the pipeline — a FINDING, as is a SHA git has never heard of; everything the
check merely could not look up is a WARNING. The era is the WATERMARK with no config knob: the
first receipt's `ts`. `--deep` adds the journal-in-commit cross-check. Layer 4.

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
the rule and a misleading one about the file. The verb is `prune`, and it is mandatory: a bare
invocation must not prune, which is why the positional takes one choice rather than defaulting
to it. Exit 0 the prune ran, 1 it could not, 2 a usage error. Layer 7. `--selftest`.

### `plugins/audit/scripts/status/audit-version.py`
Which build of the plugin is running, and whether a newer one is published - the question
a user asks before a field report, and one no documented interface answers, because a plugin
cannot ask Claude Code which copy of it is loaded. So the answer is assembled from what can be
read, each fact beside where it came from: the running copy's own `plugin.json`; the
marketplace this copy was installed from (Claude Code's install record for this exact path,
else the cache path it sits in) with what that clone offers, when it was refreshed and whether
it auto-updates, read from `known_marketplaces.json`; every installed copy by scope and
project from `installed_plugins.json` - both files Claude Code writes and does not document, so
the lines say so and a missing or malformed file is reported, never guessed around; and,
unless `--offline`, the newest release on the repository `plugin.json` names - the plugin's
only outbound call, one unauthenticated GET to the GitHub API with a short timeout, which
`SECURITY.md` states. The verdict is drawn only from what was read: an unanswered feed is
"could not be asked", never "up to date"; the update commands (`claude plugin marketplace
update`, `claude plugin update`, a restart) print only when a newer release is known and the
marketplace is. Exit 0, 1 when a newer release is published, 2 a usage error. Layer 7 (an
entry point); its cases are in `plugins/audit/tests/test_audit_version.py`.

### `plugins/audit/scripts/status/_claude_home.py`
The readers of Claude Code's own install records, moved down from `audit-version.py` so
`/audit:doctor` can reach them: an entry point is importable by nothing, and a second reader
of two undocumented files is a second answer about what is installed. `claude_home`,
`read_json`, `installed_plugins`, `marketplace_of`, `marketplace_facts` and
`installed_copies` are `/audit:version`'s, unchanged; `install_record` finds the record for
one exact install path - the marketplace and the `gitCommitSha` it was made from - and
`marketplace_source` finds the clone `known_marketplaces.json` names and the plugin's directory
inside it off the clone's own `marketplace.json`. Every reader is fail-open: a missing,
malformed or differently shaped record is None beside the sentence saying why, and the caller
says the basis is a file Claude Code does not document. `attach_usage_hint` patches a built
parser's `error` so every usage error also names this copy's version and path and, through
`applicable_copy`, the installed copy Claude Code would load for this project (project or
local scope recorded for it before user scope, another project's never) when that copy is
newer, with `/reload-plugins` as the way to it; an unreadable record is said to be unreadable.
It sits here, at layer 1, so every entry point can reach the one hook; `stamp-verification.py`
carries it. Layer 1; its cases are in `plugins/audit/tests/test__claude_home.py`.

### `plugins/audit/scripts/status/audit-lookup.py`
One question, one answer, with the pointer that lets a reader check it — instead of the
whole-plan render `audit-status.py` and the whole-journal render `audit-journal.py show`
both are, which an agent asking "why was this cancelled" had no cheaper way to reach.
`cancel <id>` reads a task's `outcome.descriptive` or a phase's `summary` (wherever the
cancel verb in `audit-task.py` actually writes the reason) and cross-checks the newest
matching `task.cancel`/`phase.cancel` journal row, matched by `details.taskId`/`phaseId`
rather than the row's shard `target`, which several tasks in one phase share. `bug <id>`
reads the bug's own `status`/`notes`/`fixedIn` — there is no separate resolution field in
this schema, so that is the honest answer rather than an invented one. A bug's `status` and
`fixedIn`, and a phase's status under `cancel`, are the DERIVED values
(`_manifest_io.derived_disagreements`); where the stored ones differ the answer prints
`stored X, derived Y (basis)`, because echoing the stored field would repeat the stale answer
the derivation exists to correct. `file <path>` is a
LOOKUP over `fileIndex`, never a search: an exact key match only, and the last entry in
`fileIndex[path]` is the answer by the index's own append-only convention (never remove
another task's id). `brief <taskId>` is `file` folded over every path the task declares,
one call at spawn time instead of one per path, and it ends with the `executor.runsGate`
reading the spawn prompt hands the executor: `hooks/_config.executor_gate_policy`'s word,
reached through `_loader` because a script may not import `hooks/`, with its basis — the key
in `.claude/audit.config.json` that set it, or that it is the default because the file or the
key is absent. A value outside `RUNS_GATE_MODES`, or a config file that does not parse, is a
refusal on stderr with nothing on stdout and exit 3, never the default, so the orchestrator
no longer reads the config for this itself. `run <runId>` (or `run latest --phase <id>`
/`--task <id>`) reads the evidence ledger instead of the manifest or journal — the bounded
render of one recorded row (`_evidence_io.row_by_run`/`latest_by_subject`, the latter keyed
through `subject_aliases` so a moved task still answers under its live id), never raw runner
output, because a gate run under `run_in_background` writes its verdict there long before its
own terminal is read again; the failing lines and `failingSuites` cross through exactly as the
writer already bounded and redacted them, never re-cut here, and an unreadable ledger file is
said rather than read as "no such run". `brief <id> --role executor|reviewer|phase` writes
the WHOLE spawn brief to a file under `stateDir` (`briefs/<id>/<start>.<role>.md`, or
`briefs/<phaseId>/phase.md`) and prints its path, so the agent is handed a path and the brief
never passes through the main loop. The executor's carries the resolved skills (area first),
the description verbatim, the files with their last declarer, the docs, the desired outcome,
the gate resolved through `meta.buildCommands`, the `executor.runsGate` reading with its
command, the filing command — one `drive-phase.py submit`, resolved against this plugin copy,
carrying on a `tdd` task the gate command that names its `tests.add` file after `--`
(`red_command`), since `submit` takes the stamp and runs the red-first helper itself — and,
only when `attempts > 1`, what the last attempt left on the record. Both reviewer briefs file
through `submit` too, the phase review's with `--head`. The
reviewer's carries the executor's return as filed for the task's current start
(byte-identical), the diff, the recorded run and the gate commands, and is refused with exit 4
(`E_REFUSED`), writing nothing, until that return is filed. The phase reviewer's carries the
request as saved (`phase.request`, or a sentence saying none was saved), one fixed question
about what the request left open, and per task its commit, files, description, filed
executor return, recorded run and `tests.gate` — an entry naming a `key:project` the plan
cannot resolve is kept and said to be unresolved — and is refused while any task has no
commit yet. It reads a filed return at the path `audit-task.py file-return` writes, both
asking `_filed_returns.return_rel` for it.
Each returns a plain "no match" — never a
nearest id or a similar path — when the manifest does not carry an answer; an id that exists but does not apply to
the question (a task that was never cancelled) is a different, legitimate answer and not a
miss. Read-only over the record (a brief is the one file it writes), exit 0 on a match, 1 on
a miss, 2 a usage error, 3 a config `brief` refuses to read, 4 a brief whose inputs are not on
the record yet. Layer 7 (an entry point reaching `_manifest_io`/`_journal_io`/`_loader`/`_areas` at layer 1
and `_evidence_io` at layer 2, for the project/config resolution `boundary_for` already
shares). `--selftest`.

### `plugins/audit/scripts/governance/_locks.py`
The lock library (layer 1): where a lock lives (`lock_dir`), what it may be called
(`valid_name`), whether its holder is alive (`pid_alive`, `judge`), what is held
(`read_lock`, `collect`), and taking or giving one back (`acquire`, `release`). Liveness,
not age, decides a stale lock, and every verdict carries the BASIS sentence that makes it
checkable. It is at the bottom of the graph because four callers ask about a lock and only
one of them is a command: `_panel_state`, `audit-doctor` and `audit-usage` each loaded
`audit-lock.py` through `_loader` (three of the edges `KNOWN_LAYER_DEBT` then carried), and
`hooks/_config.py` resolves it by path on every tool call — so the module it reaches for
should be small. `audit-task.py`'s dependency was the one nothing could see: it took the
index lock by building an argv and calling `main()` through `_panel_write._lockmod()`, so
`_deps` attributed the edge to the panel. It is an ordinary import now.

**Whose claim it is has one rule, `held_by_us`**, which `acquire` and `_evidence_io.lock_state`
both ask. A claim a process takes for its own write records a random `token`, re-entered only
by that process and by a child that inherited the token through `TOKEN_ENV`
(`AUDIT_LOCK_TOKENS`); another process of the same session waits like any holder. A claim
`audit-lock.py acquire` takes by hand is recorded `handedOff`, and its session still works under
it - the take-then-run-the-verbs flow the commands prescribe - so parallel calls under a
hand-held hold are not serialised. A claim taken with `per_call` (the panel's writes, one per
request on the server's threads) is re-entered by nobody. A claim written before tokens existed
keeps the session rule.

### `plugins/audit/scripts/governance/audit-lock.py`
The CLI over `_locks`: `acquire <name>`, `release <name>`, `status`, over the names
`_locks.valid_name` accepts — a name in `_locks.FIXED_NAMES`, or `phase-<id>` with an ASCII
id (a spelling that differs only in case from a held lock is refused, so the answer does not
depend on whether the filesystem folds case), and for tooling that is not the plugin's a
namespaced `user-<name>` under `_locks.USER_NAME_RULES`, whose own part may never be a lock name
itself and which excludes by holder, never answering re-entry — turning the library's answers
into exit codes —
a live holder is **waited out** for a bounded window and then refused (exit 3); one that is
not alive can be seized with `--takeover` (exit 4), because the old "older than 60 minutes =
crashed" rule was wrong in both directions. `--wait` overrides the window, and zero is the
old read-the-refusal-at-once behaviour, which is what a caller wants against a phase lock:
the window is sized for a lock taken for one structural write, and a lock held for a whole
run does not clear inside any window worth waiting. **A caller that already holds the lock
gets its own answer** rather than a refusal or a fresh acquisition — the work may proceed and
the release stays with the hold that took it, since releasing on that answer would drop the
lock out from under the step still using it. `shell_code()` is where that answer collapses to
0 for a shell, and only for a shell: a process status says whether the step may go on, while
a caller that must know whether this call took the lock is the one reader that cannot be told
the two apart. `--session`/`--pid` override the identity written into the lock for testing.

### `plugins/audit/scripts/governance/_invariants.py`
The post-hoc reader of `reference/orchestrator.md` (layer 4). Both READMEs split the
plugin's rules into what a hook ENFORCES and what the model FOLLOWS, and the second table's
last column names, per row, what evidence would catch a breach — `post-hoc` where git, the
shard, the journal or the ledger already holds it. This module reads that evidence, check by
check — `CHECK_NAMES` is the list and `verify-invariants.py --all` prints it: a task commit
staged only its own `files`, its phase's manifest file and the two records beside it
(`git show --name-only`); an **audit-state** commit staged those records and *not* the task's
`files`, found through the journal's `audit.state.committed` rows because nothing in the
manifest names such a commit; a **manifest-index** commit staged the shared index and the
journal holding its own row and nothing else, found the same way through `audit.index.committed`
rows — each row naming its commit by `details.commit` or, when the row is inside that commit, by
the `Audit-Row` trailer its `commitNonce` matches (`_invariants.commits_carrying`); no push, no forced
update and no stash touched the phase
branch (the remote-tracking refs, the branch's own reflog compared pairwise for ancestry,
and `refs/stash`); every manifest state the phase COMMITTED still validates (each commit's
index and shards reassembled through `git show` and run back through `_manifest_rules`); a
`risk: "high"` task ran on neither a declared nor a metered `haiku`; and `phase.baseRef` is
an ancestor of the parent `_branch.parent_branch` resolves.

Every breach is built with `found(line, subject, sha, local)`, `result()` refuses one that was not,
and `test__invariants.py` walks this file's syntax tree so a bare sentence fails CI: the sentence is
what a reader is shown and the `keys` beside it — the subject that broke the rule and the commit it
is recorded against, resolved to the full id through git — are what a baseline matches, so a
reworded template or a count that moves between runs changes the output and never the match. A
validator finding's subject is `_manifest_rules.finding_subject`: the CODE of the rule that raised
it, its locus and the ids it quotes, with the sentence and any quoted allowed-values list taken
out. Every validator finding is built with `_output.finding(code, text)` — a `str` subclass, so
every caller that prints, joins or compares findings reads it unchanged and only this reader asks
for `.code` — and `test__output.py`'s `fc` cases follow every call `validate()` reaches, across
modules, and fail a finding site built without a code (an append, an extend or `+=` of a list or
comprehension, an assignment of one, or a list returned in place), or two sites sharing one. The
ADO hierarchy findings carry `_ado_parent`'s own rule code (`crossrefs.ado_parents.A1`...). An
allowed-values list leaves the key bracketed or spelled `one of 'a', 'b'`, and a finding with no
`: ` keys on the dotted path it opens with. The clone id is published by linking a finished
sibling onto its name, and a baseline write with a local breach and no readable id is refused. The live
pairing re-check keeps only the rows naming this phase's own tasks (`own_pairing_findings`).

**The baseline** (`invariants-baseline.json` beside the manifest) lives here rather than in the
command because two surfaces give a verdict over these checks, and `counted_breaches` is the one
answer both read. `apply_baseline` compares on `(phase, check, subject, sha, clone)` — `clone`
set only on a local entry — and sets an entry
aside, with the reason, when this run could not have seen it again — its phase was not examined,
its check had a gap, or it was read from another clone's own evidence (a breach marked `local` — a
reflog, the stash, a remote-tracking ref, the usage ledger — carries the id of the clone that
wrote it, and goes stale only there); only the rest can be reported as no longer matching, each
with what git says about its commit. `write_baseline` refuses while a phase it covers is in flight,
takes the `index` lock around its read-then-write and refuses a hold it did not take itself, keeps
every set-aside entry, and returns what it removed. The baseline is a human's commit outside any phase commit,
since each of the plugin's commit classes would breach its own scope by carrying it.

`audit-state-scope` and `index-scope` sit next to `commit-scope` rather than at the end
because each asks that check's question about a different commit, and the three allow-lists
differ entry by entry — a task commit may stage the task's `files` and an audit-state commit
may not, and a manifest-index commit may stage the one path both the others forbid and
nothing whatever besides. Their `no-basis` case is shared and is its own: with
`journal.enabled` false there is nowhere either commit could announce itself, which is *not*
evidence that none was made. `index-scope` gives the phase's own manifest file its own breach
sentence — the mirror of the one the other two write about the index — because the pair in
one commit is the shape parallel phases conflict on, and reporting it like a stray README
would price the expensive mistake as the cheap one.

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
`in_evidence()` is the membership question that pairs with it — is this path inside the record —
and its prefix test carries the separator, a boundary its cases assert from the outside, since a
prefix test without it admits every sibling whose name merely starts the same way.

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
and a bare list could not tell them apart. The **parse** is `_journal_io.rows_from_text`'s and only
the **counting rule** is local, so a row the chain grades and a row this returns can never be two
different things. `rowFiles` names, at each row's own index, the basename of the file it was read
from, so a caller that must say *which* file holds a run reads it from this one read instead of
walking the directory again with a decode of its own.

**Every row is hash-chained, with the trail's chain and not a second one.** `append_row()` links
each row onto the file's tail — `prev`, then `hash` over the canonical row, seeded from the file's
own basename by `genesis_prev()` — and `verify()` reads the links back. All of it is spelled with
`_journal_io`'s `row_hash`, `genesis_prev` and `canonical`: a ledger with a chain of its own
invention would be a second answer to *was this row edited*, free to disagree with the trail beside
it. Before this, the record of the **measurement** was the one committed file here a string replace
could edit with every verdict in the tree staying green. The append now takes the journal's file
lock and **raises** when it cannot — `prev` is read off the tail, so two writers that both read it
would write the same link and manufacture a break that reads exactly like a deleted run.

**It does not replace the journal anchor, and the module says what each layer reaches.** The chain
catches an edited row, a deleted or reordered one, and a whole file dropped over another writer's —
and it is the only one of the three that answers with a FINDING. The anchor `record()` writes is
the weaker layer, not the fallback: it is a warning, it is compared only against the newest trail
row naming the file, and a row written through `append_row()` alone is anchored by nothing. The one
rewrite the chain cannot see — every row rewritten and every hash recomputed forward — is git's.

**A row written before the chain existed is a counted warning, never a finding.** Grading those as
tampering would turn this check's first run red in every project that upgrades, and a check whose
opening verdict is a wall of findings nobody means to act on is one its reader learns to skip. The
gap closes itself: `link_after()` hashes an unchained row to make the `prev` of whatever follows,
so the next recorded run puts every row before it under the chain. What *is* a finding is an
unchained row **after** a chained one — without that the chain is opt-out, since deleting two keys
would put a row back outside it — and the finding names the innocent reading (an older copy of the
plugin appended it) rather than asserting forgery, because nothing there can tell the two apart.
`audit-journal.py verify` is the command that prints both records' verdicts and exits non-zero when
either has findings.

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

**`full_status()` answers the third place's own question from the ledger alone**, never from a
manifest pointer: WHOLE only when a scope-`full` row that is green, measured, clean and running
`meta.fullGate` verbatim has a head `_worktrees.merged_into` (git ancestry, never string equality)
finds containing the phase's `mergedHead`, PROVISIONAL when every such row falls short of that,
UNKNOWN when the phase carries no `mergedHead` or git itself could not say, and NOT_DECLARED when
the plan names no third place at all.

**`row_is_red()` is the one reading of "this run exited red"**: every `status` but `passed`
(`RUN_PASSED`), because `run-test-gate.py` exits 0 exactly then — so a status no writer has
produced yet, or none at all, is red rather than a pass nobody measured. The measurement rule
above, `full-gate.py`'s `--learn-from` refusal and `import-evidence.py`'s printed command all ask
it rather than comparing the word themselves.

**`pin_suite()` is where a runner's spelling of a suite becomes a tracked path.** A runner names
a suite from whatever directory it was started in, and a derived gate, a coupling and a bug spell
it from the project root. `suite_listing()` asks `git ls-files` from the project once per reader,
and `pin_suite()` normalizes the spelling (`project_relative()`: an absolute one inside the
project becomes relative, one outside it is refused), then keeps the ONE path `resolve_named()`
matches among the tracked files plus the spelling itself when it exists from the root — so a
spelling on disk that also has deeper tracked twins pins to none of them, and a spelling that
sibling packages both end in pins to none of them; either way the reason names the candidates.
Where git cannot list, a spelling on disk from the root is kept as written and any other is
refused naming the listing failure; a path holding a control character is refused
(`shell_unsafe()`). `pin_suites()` is the all-or-none form `audit-task.py add --failing-from`
narrows a fix task's gate with. `selection_miss()` pins each named suite before asking whether a
derived gate listed it, so a name that pins to no path, or to several, is a
`SELECTION MISS not asked of` line rather than a listed suite; `full-gate.py` pins each miss
before `couple` and `bug-add`; and `own_miss()` is the one reading of "this row lists that suite
as its own miss", which `full-gate.py`'s catch credit and `couple --caught`'s refusal both ask.
Crediting a catch to a coupling is a different question — which coupled key a name fits — and
both of those ask `resolve_named()` over the coupled keys directly.

### `plugins/audit/scripts/governance/_gate_derive.py`
The gate helpers' one home, and a pure `derive()`.

`is_shared_key`, `path_scoped_sibling` and `repointed` used to live only inside
`audit-task.py`, answering the same three questions a TASK's own narrow gate is
derived from. A PHASE-level derivation needs the identical questions asked one
level up, and an entry point cannot import another entry point — so the phase
side could only ever have copied the three. They moved here, unchanged, and
`audit-task.py` keeps thin aliases so no existing caller or case had to change
its spelling.

`derive(manifest, phase, facts)` is the phase-level answer: what
`meta.phaseGate.mode` computes for one phase's sign-off gate, replacing only
the part of the wide default that is not `meta.phaseGate.always` — read once,
through `_manifest_phases.phase_gate_default`, so a fallback can never run
fewer suites than `/audit:phase add` would already have written. It is PURE:
every observation (a listing's exit code and paths, the installed version's
answer, which paths changed since `baseRef`, the newest red phase-scope row's
named failures, the plan gate's exempt verdict per touched file) arrives
through `facts`, supplied by the caller — no subprocess, no git, inside the
function itself.

`resolve_shape(phase, build, derived_cfg)` is where the path-scoped shape a
narrowed gate repoints comes from — a sibling task's own `path_scoped_sibling`
entries FIRST (evidence the runner already accepted them), and only when none
exists, `meta.phaseGate.derived.spelling` SECOND, when it carries a literal
`{paths}` placeholder (ignored, with a printed reason, when it does not).
Neither existing is `phase-no-spelling`, unchanged. `derive()`'s own result
carries `shapeSource` — the sibling's task id, or the literal
`meta.phaseGate.derived.spelling` — so a reader can tell which of the two
supplied the shape; a spelling-sourced shape is filled by literal `{paths}`
substitution rather than through `repointed()` (its placeholder is not a
path-shaped token that function would recognize), the resolved paths
shell-quoted through `shlex.quote` exactly the way a listing command is.

**`derived-empty` has TWO triggers, and `derive()` is the only place either is
computed.** The first: `meta.phaseGate.derived.listing.all` ran, exited 0 and
named no suite (caught by `_full_listing_empty`, before coupling/importers/
changed/last-failed ever run). The second: the shape came from
`meta.phaseGate.derived.spelling` and, after every arm has had its turn,
`test_paths` is still empty — a sibling-sourced shape cannot reach this
(the same task that supplies it already contributed a path through
`_tests_add_arm`), but a spelling-sourced one carries no such guarantee, and
substituting `{paths}` with nothing would make the gate mean either the WHOLE
suite or NOTHING depending on the runner, silently. Both triggers return
`attribution: None` alongside `basis: "derived-empty"` — the SAME word, so a
caller renders the SAME honest wide line regardless of which one fired.
`attribution` (`{testsAdd, coupling, importers, changed, lastFailed, union}`)
is `derive()`'s own per-arm breakdown, present ONLY when `narrowed` is true —
`None` for EVERY wide basis with no exception, `phase-no-spelling` and both
`derived-empty` triggers and a full-suite resolution alike: a full-suite
`test_paths` is real (the union of `tests.add` and coupling, computed before
the importer/changed/last-failed loops even run) but it is not what the wide
gate runs, so it is not attributed either. `derive-phase-gate.py`'s renderers
read ONLY this dict, keyed off `result["narrowed"]` and `result["basis"]` —
never off whether `attribution` happens to be `None`, because a second,
independent computation of the same arms does not know every widening
trigger `derive()` knows, and would report a narrowed-looking breakdown for a
gate that is actually wide the next time a trigger is added. That second
computation used to exist here, as `derive-phase-gate.py._breakdown()`; it is
deleted, and `attribution` is the only breakdown this plugin computes.

Four arms, each additive to the test-path set before it is re-pointed through
the sibling's own spelling: the union of path-scoped paths in each task's OWN
gate (never a task that fell back to its phase's wide one — that fallback IS
the wide gate, and reading it as evidence of a narrow one would be the
derivation citing itself), every `meta.coupling[].test` whose `sources` overlap
the phase's own touched files, an importer listing (only trusted when its
`verifiedOn` answer matches the machine asking, dg23, and only narrowing when
its paths are a **strict** subset of the full listing — equal to the full
listing means the wide gate already **is** the narrow answer, dg1), and the
always-on additions (changed test files, the last-failed suites). `meta.
phaseGate.smoke` is added unless every file the phase touched is exempt or a
test file itself — **never** decided by `meta.runtimeBoot.appRootPath` (dg10):
a source file outside an app's own root is still a source file. No path-scoped
sibling, or nothing to narrow to after all four arms, falls back to
`meta.phaseGate.always` plus the default's non-`always` part — never an empty
gate. Every narrowed answer's basis carries one pinned sentence (dg4):
"selected by import graph and recorded couplings only" — naming the ceiling on
what this derivation is allowed to have used.

### `plugins/audit/scripts/governance/verify-invariants.py`
The CLI over it: `verify-invariants.py <manifest> <phaseId>`, or `--all` for every phase that
has started (a branch, a `baseRef` or a recorded commit). `--json` for the whole answer,
`--project` for the directory holding `.claude/` and the journal. Exit 0 answered, 1 at least
one breach, 2 usage error or unreadable manifest — and a missing basis is deliberately exit 0
with the word in the output, because sign-off deletes the phase branch and a gate that fired
on absent evidence would fire on every finished phase. Wired into Phase sign-off and into
`/audit:status --gate --fail-on invariant-breach`. `--write-baseline` records the current
breaches in `invariants-baseline.json` beside the manifest, and `--baseline FILE` names another
file; once one exists the CLI prints only the breaches it does not hold, counts the ones it does,
and exits 1 only on a new one. Everything about the baseline itself — its keys, what is set aside,
the in-flight refusal, the lock — is `_invariants`', which is what lets the gate give the same
verdict.

**`landing-committed`** is `_invariants.landing_committed`, the last of `CHECK_NAMES`, so this
CLI and `/audit:status --gate` read one answer. For a phase with `mergedAt` set it reads
`status` and `mergedAt` off the phase's record in each plan file (the shard, and the index when
it is a different file) as the working tree holds it and as HEAD commits it, and a field that
differs is a breach naming the file and both values - the landing's stamp left as an edit. It
compares the stamp, never the file's dirtiness, so other edits to the plan are not this breach;
a phase that has not landed is `not-applicable`. It is the one check that reads the working
tree, so its answer is about the tree it runs in. The `ln` cases in
`plugins/audit/tests/test__invariants.py` hold it at the library, and `lc` in
`test_verify_invariants.py` through the CLI.

### `plugins/audit/scripts/governance/_scoped_commit.py`
Everything the three **commit-a-narrow-allow-list** commands (`commit-audit-state.py`,
`commit-manifest-index.py`, `commit-task-work.py`) share, so that none holds a second copy of it:
the git runner that keeps stderr (a refusal is the only thing a human can act on, so
`_commit_trail._git`'s `DEVNULL` is wrong here), git's own line shape, `under_any` over
`_invariants._under`, the working-tree read that decides **before** anything is staged, the index
read that refuses **after** it (with `--no-renames`, so a staged rename from outside the list names
its source), and the one answer shape and renderer the commands print.

**How each path is staged, and how the index is put back.** `classify()` asks git what it holds
for each allowed path and `stage()` stages it accordingly — `git add -u --` for an index entry,
`git add --` for a path only on disk, both for a directory holding tracked files (its tracked
members with `-u`, its untracked ones git does not ignore by name, because a directory gitignored
as a whole is not reported by `check-ignore` and `git add -- <dir>` refuses it), neither for a path
only HEAD holds (a staged rename's source, a staged deletion) — and `stage_and_commit()` is the
whole sequence: snapshot the allowed paths' index entries (`ls-files -s`, every stage of a conflict
kept, intent-to-add read from `status --porcelain=v2`), stage, read back, commit with the list as
the pathspec, and on any refusal put the entries back through `update-index --index-info`, whose
removal lines carry a zero id as long as the repository's object format's (SHA-1 or SHA-256).
Stat data and the skip-worktree bit are not restored, and the sentence it prints says only what is.
The one commit a pathspec cannot make is one carrying a file taken out of the index with `git rm
--cached` and then ignored — a pathspec commit reads the working tree and records nothing for it —
and `commit_from_index()` builds that one in a temporary index (`read-tree` of the HEAD read
before staging, the allowed entries over it) and runs a real `git commit` with `GIT_INDEX_FILE`
pointing at it, so it carries exactly the allow-list and the project's `pre-commit` and
`commit-msg` hooks run on it as on every other commit; a refusing hook leaves the real index
untouched. HEAD is checked against the one read before staging just before the commit, and the new
commit's first parent after it; a mismatch there is refused with both SHAs named, and nothing is
reset.

**No command can import another** — nothing may import a hyphenated entry point — so this
module is the only place they meet, and a second spelling of a refusal rule is how one commit
comes to carry what another forbids. Layer 5: it reads `_invariants` (L4) for `_under`,
which is the one answer to "is this path inside that entry" that the writer and the after-the-fact
checker both have to give.

**What is deliberately not here: the allow-lists.** Each command derives its own, and they differ
in exactly the entries that matter — one may stage the phase's shard and the records beside it and
never the shared index, another may stage only the shared index and the journal file holding
the row that names its commit, and never a phase's file. A shared builder taking a flag would be
one function holding several safety properties, which is the shape in which a widened list stops
being noticed.

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

**Never an empty commit**, and a fixed literal in the **scope** position. Nothing staged means no
commit and a line saying so — a stream of empty commits is how a record stops being read. The
commit itself reads `chore(audit-state):` — `chore` because commitlint's default type-enum has to
accept it or a repository with husky rejects the commit *after* the file is staged, and
`audit-state` sits in the scope because a task commit's scope is its phase id while its type comes
from `meta.commit.type`, which a manifest may set to anything. `git log --grep audit-state`
therefore separates the two commit classes for ever.

**And the subject after the colon opens with a fixed lowercase word** — the line reads
`chore(audit-state): phase P6 — …`. This is the second half of the same repair: `chore` satisfied
commitlint's default `type-enum`, and the very next default rule refused the commit anyway.
`subject-case` forbids a subject that *is* sentence-case, start-case, pascal-case or upper-case,
and a phase id leading an otherwise lowercase sentence is sentence-case exactly. Aiming at every
one of those cases rather than at the one that bit is the point, because meeting the defaults a
rule at a time is what made this a second visit: each of them is computed by a transform that
capitalises the subject's first character, so a lowercase-initial subject is out of reach of all
of them. The word is this command's and not the caller's — it sits ahead of `--subject`, so
nothing a caller passes can put a capital back in first position — and the phase id stays
**uppercase** one word further in, since the id was never what the rule objected to, its position
was. The shape is unconditional and deliberately **not** read from `meta.commit`: that block holds
a default type and a trailer, records nothing about which commitlint rules a repository
configures, and a fixed spelling no manifest can move is exactly what this buys.

**It anchors itself in the trail, from inside the commit.** Before committing it appends an
`audit.state.committed` journal row whose `details` carry `commitNonce` and `phaseId`, ends the
commit message with an `Audit-Row: <nonce>` trailer, and stages the row with the rest — so the
row is in the commit it names and the run leaves no trail behind (`_scoped_commit.commit_with_rows`,
shared by every scoped commit). A row inside a commit cannot hold that commit's SHA, which is
why it holds the nonce; `_invariants.audit_state_scope()` resolves it with `git log --grep`, which a
rebase does not break. A commit carrying the trailer is graded only when its subject opens with the
class header (`_invariants.STATE_HEADER`, `INDEX_HEADER`) and the trailer is in its last paragraph;
any other carrier - a squash merge, or a commit that gained a paragraph after its trailer - is
reported as a gap naming it and the test it failed, and is never graded. A commit refused after the row was written — a hook, git itself — leaves an
`audit.commit.withdrawn` row naming the nonce, and a reader drops a withdrawn nonce instead of
reporting a commit that does not exist. Because the row is inside its commit, a journal holding
only other writers' rows is committed like the other two records; a second run finds nothing
uncommitted. The row's target is the **evidence directory** and deliberately not the phase's
manifest file, because `_recorded_states()` reads every row naming that file as a *write* to it
and a commit is not an edit. The append is fail-soft (`_journal_io.append`'s contract) and a row
that could not be written is printed: a commit that happened must not be reported as not having
happened.

### `plugins/audit/scripts/governance/commit-manifest-index.py`
`commit-manifest-index.py <manifest> <phaseId>` — **commit the manifest INDEX on its own, or say
there is nothing to commit.** `--project` names the directory holding `.claude/` and the
records, `--subject` supplies the commit subject after the conventional prefix, `--takeover` takes
a lock a human has confirmed is dead, `--json` prints the whole answer. Exit 0 it ran, 1 it could
not, 2 usage error, 3 the lock is held by a live process, 4 the lock is stale.

**The gap it closes.** In the sharded layout the index holds `meta`, `fileIndex`, `bugs[]`,
`deferred`, `proposals` and the phase stubs. `/audit:task add --files …` writes `fileIndex` there
and `/audit:phase add` appends a stub — while step 4c forbids a **task** commit from staging the
index and `commit-audit-state.py` refuses it too, both correctly and for the same reason. So
nothing committed it: the structural edits accumulated in a working tree until somebody noticed.
Reported from a live project, committed by hand three times in one evening.

**Why a commit of its own rather than a wider allow-list somewhere else.** The sharded layout
exists so two phases can run in parallel without meeting on one file. A commit carrying a phase's
work **and** the shared index cannot be landed, reordered or dropped without taking the work with
it; a commit carrying the shared file **alone** can be landed, cherry-picked or thrown away and
re-derived (`/audit:task scope` rebuilds `fileIndex`), and its conflicts stay confined to the file
it carries. Widening `commit-audit-state.py`'s list would have satisfied that script's own
verification — its allow-list and its staged set are one list, so nothing there could notice —
while destroying the property both scope checks exist to defend.

**What it stages: the index, and the one journal file holding the row that names the commit, and
nothing else.** Not the shard, not the rest of the journal, not the evidence, not the task's
`files`. The allow-list is the index; `commit_with_rows` adds the row's file to it, and nothing
else widens it. Each path is staged **explicitly** (`git add -- <path>`, never `git add -A`), and the index is read back
with `git diff --cached --name-only` and compared against the same list **before** the commit —
and read **before** staging too, so work somebody else had already staged is refused while the git
index is still exactly as it was found. Both reads are `_scoped_commit`'s, shared with its sibling.

**Under the index lock, which its sibling does not take** — the asymmetry is the point. That
command commits a phase's own shard, which only that phase writes; this one commits the file every
structural command writes, so a concurrent `/audit:task add` between the read and the commit would
put half an edit into git. It is the same lock `audit-task.py` and `set-priority.py` take, borrowed
rather than retaken when the caller already holds it.

**In the single-file layout it refuses, by name.** There the manifest *is* the index —
`_invariants.manifest_files()` returns the identity pair — so the ordinary commits already carry it
and this route would commit the same bytes twice. The identity pair is the test, never a filename
guess. It refuses by declining and saying which state it is in, and still exits 0: a single-file
project has done nothing wrong by calling this, and a non-zero exit would make every single-file
sign-off read as failed and get the step deleted within a day.

**Never an empty commit**, and a fixed literal in the **scope** position. `chore(audit-index):` —
`chore` because commitlint's default enum has to accept the type or a repository with husky refuses
the commit *after* the file is staged, and `audit-index` in the scope because a task commit's
scope is its phase id and its type comes from `meta.commit.type`, which a manifest may set to
anything. `git log --grep audit-index` therefore separates the three commit classes for ever.

**And its subject opens with the same fixed lowercase word**, against the identical defect:
with the phase id first the subject *is* sentence-case, which commitlint's default `subject-case`
refuses along with start-case, pascal-case and upper-case. The reasoning is spelled out under
`commit-audit-state.py` above and is not restated here; what is specific to this writer is that
the word names the phase **without** claiming to be scoped to it — the conventional scope says
`audit-index`, and that is what the commit is scoped to, while the subject's phase is attribution.

**It anchors itself in the trail, from inside the commit.** Before committing it appends an
`audit.index.committed` journal row whose `details` carry `commitNonce` and `phaseId` — both on
`_journal_io.DETAILS_KEYS`, checked by a case rather than assumed, because that allow-list drops an
unknown key in silence — and adds the ONE journal file that row landed in to its allow-list, so the
commit carries the index and the row naming it. A journal file is named for one writer and one
worktree, so it is not a file two phases meet on. The row is the only handle anything has on such a
commit, and it is what `_invariants.index_scope()` resolves through the `Audit-Row` trailer to find
these commits and grade them. `<phaseId>` throughout is **attribution and not scope**: the index is
shared, and the phase id says which run made the structural change.

### `plugins/audit/scripts/governance/commit-task-work.py`
`commit-task-work.py <manifest> <taskId>` — **commit one task's work, staging what that task
declares and refusing the rest.**

**Why it exists.** The successful task commit was the one git operation this plugin described in
prose and did not script. `reference/orchestrator.md` step 4c spells the staging list, the
pathspec, the message shape and the exclusions in a paragraph the model reads at the end of every
task, under time pressure, after the work is already done — and what a paragraph gets in that
position is generalisation. Four scope breaches on one program came from widening two words of it:
a file "obviously" part of the change, a sibling the editor had also touched, the shared index
because the phase file was allowed. Prose cannot refuse; this can.

**What it stages.** Exactly the four things step 4c allows, each named in the output: the task's
own `files` (a `:line-range` suffix stripped, because git has never heard of one), the phase's
manifest file, the journal directory and the evidence directory. Nothing else, and the manifest
**index** explicitly not — a task commit carrying the index is what makes two parallel phases
conflict on merge. `_invariants.commit_scope()` re-derives that same list from git afterwards, so
these commits are graded by something that did not make them.

**How the exclusion is enforced rather than intended.** Paths are staged explicitly (never
`git add -A`), the git index is read *before* staging so work somebody else had already staged
cannot ride along, it is read *back* afterwards against the same allow-list, and the commit itself
carries an explicit pathspec. A path outside the list is **named** in the refusal, and a staged
index gets a sentence of its own — reporting the expensive mistake in the same words as a stray
README is what makes a reader skim past it.

**Each path is staged by what git holds for it**, through `_scoped_commit` (below the section on
that module): the source of a staged `git mv` or `git rm` is committed as the rename or deletion it
is, a tracked file under a gitignored directory is staged as the tracked file it is, an untracked
declared file git ignores is refused by name before anything is staged — `-f` is never passed — and
a record path git ignores is refused in words of its own. A refusal after staging puts the allowed
paths' index entries back from a snapshot taken before it.

**Bound to the verdict it was measured under.** It refuses unless the task's newest evidence row
(the rows carrying its task id) is `passed`, was measured under the gate the task declares now
(the row's steps, their dropped count and `gateDigest` — the entries beside what
`meta.buildCommands` resolves them to, `_evidence_io.gate_digest()`), and its
`testedState.scopeDigest` still matches the files being committed. That digest is
`_tree_stamp.scope_digest()`: the scope is normalised once by `declared_scope()` (line suffixes
stripped), `scope_digest()` expands a directory into the files git lists under it (one it lists
nothing under is hashed as a defined empty entry), and the recorder's own paths are left out on both
sides; `scopeListDigest` beside it tells a changed declared list from changed contents. HEAD and
the dirty-path digest are not compared, because a sibling commit between a task's gate and its
commit moves both. A task nothing can measure — its task gate cleared on purpose
(`gateBasis: cleared`), or its own `tests.gate` and its phase's `testGate` both empty — commits and
says it is bound to no verdict, in a sentence that says which of the two it is, unless a red was
recorded under its gate after the last green: the `empty-gate` row `--record` writes for such a gate
does not retire that red, and only a green or an override with its reason does. The same row under
a gate that declares entries now is refused as a gate changed after the measurement. An unparseable
ledger line
refuses unless it names another task. `--override-verdict <reason>` commits anyway and writes an
`audit.task.verdict-overridden` journal row; it is refused while the journal is off. Which gate
measures a task is `_manifest_io.gate_entries()` — the one answer `run-test-gate.py`, the panel's
gate badge, the report and the demo generator all read.

**It does not write `task.commit`.** The SHA is only knowable after the commit this makes, and the
shard is inside that commit, so writing it here would need a second commit or an amend — which
step 4c forbids. The SHA is printed and `/audit:task done <taskId> --commit <sha>` records it,
riding along with the next commit exactly as step 4c already says. It anchors itself in the trail
with an `audit.task.committed` row in the meantime, which is redundant the moment that verb runs;
the row — and an override's row — is written before the commit and carried by it, keyed by the
commit's `Audit-Row` trailer, and an override whose row cannot be written is refused before
anything is staged.

**It takes no lock**, and that is the asymmetry with `commit-manifest-index.py` rather than an
omission: this commit touches the phase's own shard, which only that phase's run writes, and the
task's own files, which the plan gate has already bound to one task.

### `plugins/audit/scripts/governance/run-test-gate.py` (v1.4.2)
Runs a phase's `testGate` and answers the two questions an exit code cannot.

**Did the gate change the tree?** `git status --porcelain -uall` before and after. A gate is a
MEASUREMENT; one with side effects has answered a different question than the one asked, and
a commit built on it carries work no task owns and no review saw. Any difference prints
`GATE MUTATED THE TREE: <files>` and refuses **regardless of the gate's own exit code**.
Measured live: a docs task's `pre-commit run --all-files` rewrote five backend source files —
`isort` and `black` are fix-in-place and reported `Passed` *because* they had.

**Whose writes, though — the bracket has no pathspec.** It describes the whole
repository, so every write landing in its window is caught, including a **sibling executor's**,
which this file's own orchestrator reference invites by running tasks with disjoint `files` in
parallel. Measured live on a project whose gates are all read-only (`eslint` with no `--fix`,
`tsc --noEmit`, `vitest run`): one run named a file owned by a *different* task, another went
red across dozens of paths and green on an identical re-run — and the verdict refuses the commit
step, so a false positive there halts a correct run. The changed set is therefore split by the
`files` the work under test declares. Paths **inside** it are the gate rewriting its own
subject: `GATE MUTATED THE TREE`, unchanged, still refusing. Paths **outside** it print
`TREE CHANGED OUTSIDE THIS WORK` and do **not** refuse — porcelain reports *what* moved and
never *who* moved it, so a gate writing outside its subject and a second session writing
anywhere produce the same two snapshots, and the line names both readings. That is a real cost
stated rather than hidden: the incident that motivated this check lands in the reported half under `--task`, and
what still refuses is the half where a gate's verdict is a claim about bytes it produced
itself. With no declared files there is nothing to sort by, so both halves are `None` and the
whole set is attributed to the gate — the direction a guard may be wrong in.

**`-uall` is load-bearing, and its limit is stated rather than left to be assumed.**
Without it git collapses a **wholly untracked** directory to one `?? dir/` entry, so a
fix-in-place gate that *creates* a file inside one moves no porcelain line and the bracket
answers `treeMutated: []` — the value that means KNOWN CLEAN. That is the day-one shape of a
subject tree nobody has committed yet, and of a new source directory in one that has; the three
other porcelain readers here (`_journal_io._git_status_sets`, `commit-audit-state`,
`guard-bash-writes`) already pass it. What the flag does **not** buy is content awareness:
porcelain reports status, never bytes, so a *rewrite* of a file that was already untracked keeps
its one `?? path` entry and is invisible to this comparison with the flag exactly as without it —
the same limit `dirtyDigest` states for an already-dirty tracked file. Both directions are pinned
by cases, so the flag cannot be read as having repaired what it did not touch.

**Did anything actually run?** Runners that report their own step count are read and the count
printed; zero is `NO CHECK RAN`, which is not the word green. The same live run, narrowed to
the task's two markdown files, SKIPPED every hook on a Python-only config: exit 0, nothing
verified, task done. One design, both failure modes, and the exit code separated neither from
a verdict. A runner that does not report a count yields `None`, printed as not-knowable —
guessing zero would refuse a passing gate and guessing one would bless a skipped one.

**And the count vocabulary was one entry wide, which made a documented rule unreachable.**
Only `pre-commit` reported a step count, so jest, vitest, mocha and pytest all answered
`None` — and with it, `orchestrator.md`'s "gates could NOT run … zero tests collected"
distinction had nothing to turn on. Each of those runners prints one line of its own arithmetic
and it is now read, matched on the **output** rather than on the command, because a gate entry
is as often `npm test` or `make check` as it is the runner's own name (`_STEP_WORDS` is still
asked first, so a `pre-commit` gate wrapping a test hook keeps counting hooks). Only the words
that mean a check EXECUTED are counted: jest's `N total` includes skipped tests, so reading it
would bless the gate that skipped everything. A step that exits **non-zero having run zero
checks** is `could-not-run` — infrastructure, not the task's failure — and prints
`GATE COULD NOT RUN` instead of recording a red suite against the task's name. Measured live:
`mongodb-memory-server` could not bind a port in a sandbox, the suite died at exit 48 with no
test executed, and the ledger recorded GATE RED.

**`render` had no arm for either no-verdict word at all**, which is why widening the count had
to close that first: with `failed` empty and the tree clean, a run that never started, and one
stopped at its bound, both fell through to `GATE GREEN` and exit 0 while `status` said otherwise
— a false red turning into a false green is strictly the worse trade. `GATE COULD NOT RUN` and
`GATE TIMED OUT` are printed from the steps' own `outcome`, never from the status word, so a
run that is two things says both.

**`observations.countsBasis` is written here for the first time.** It has been copied into every
evidence row by `_evidence_io.row_for` and rendered by the report and the panel since the ledger
existed, while nothing ever set it — a three-valued count shipping without the basis that
explains its unknown arm. It says which steps were counted, which printed no summary this reader
can parse, and, on a mixed gate, that the total is a floor and not a size.

**A step that did not come back zero now says WHICH checks failed**, in `steps[].failing` with
`steps[].failingBasis` beside it. The text was in hand all along and was thrown away: `_shell`
merges stderr into stdout, `ran_count` reads it and `files_named` scrapes it, and then it reached
neither the result nor the row — so a red row named the failing gate **entry** and never a failing
**test**, and two projects answered that by writing their own failing-test reporter around the
gate. One of them recovered the names twice out of an artefact the next run overwrites, which
makes the obvious reflex — re-run and read the output — the one action that destroys the evidence.
Where `summary_count` recognises the runner, `_FAILURE_READERS` parses the names it gave the
failing checks; where it does not, the row keeps a capped tail of the output instead of silence.
The basis is what tells those two apart, and neither travels without the other. Three things bound
it: the list is cut to `_evidence_io.MAX_FAILING` **by the writer**, each line is held to
`_journal_io.MAX_VALUE_CHARS`, and only steps with a non-zero exit carry it at all — a row is
hash-chained, so a field with unbounded content is a row with unbounded size. Every line goes
through `_journal_io.redacted_text` on the way in, which is `repo_relative_or_token` under each
path token: a stack frame naming a home directory is the CWE-532 leak the journal was repaired for
arriving through a new door. The terminal prints the same lines **raw**, because a path rewritten
to the outside token is one the operator cannot open, and only the committed file may never carry
it. It is an observation beside the verdict and not a second verdict — the status word, the exit
code and the `failed` entry list are exactly what they were before the names existed.

Exit 0 passed / 1 a command failed, or the gate rewrote a file the work under test declares,
or nothing ran, or a step reached no verdict — a runner that never started, one the OS ended,
one stopped at its bound — or a stop signal cut the run short before every step had reported /
2 the gate could not be asked.
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
for a record to make — the preamble names both ids, and a `graded by:` line sits under the verdict
banner without changing the banner's literal. Absent and empty are one answer, except that a gate
**cleared on purpose** (`tests.gateBasis: cleared`, what `--gate-clear` writes) resolves EMPTY at task
scope, as `commands/task.md` promises; an unknown task id is an error rather than a quiet fallback,
the distinction `owned_files` already draws.

**What did not finish is separated from what failed.** A timeout and a failure to *start* used to
be one answer — both were swallowed into `except Exception` and reported as exit 127, so "the suite
hung" and "the binary is missing" arrived identical. They are different repairs, so they are
different words, and neither is read out of an exit code: 124 and 127 are codes a real command may
return on its own, so the category comes from what the wrapper observed and travels beside the code.
A missing binary under `sh -c` is read off the **shell's own diagnostic** beside the 127 —
`no_verdict_signature()` holds each spelling a case holds the tool's own output for, and vitest's `No test files found` beside its
exit 1 — and only where the output carries no end-of-run report, so `reached_a_verdict()` stays the
guard for a runner whose exit status is a count. A bare 127 is still a failure, pinned by a case.
A jest worker killed by a signal leaves jest's own exit at 1, so that kill is read from jest's report
(`jest_worker_signal()`), and only when every failure it names is one; the coverage question is asked
only of steps that reached a verdict.

**The process GROUP is torn down, not just the child.** `subprocess.run(timeout=)` kills the direct
child, and under `sh -c` that child is the shell: `npx` → `node` → its workers outlive it, keep
running and keep **writing** — into the very tree this script is about to describe. So a step is
spawned into its own session (or process group on Windows) and stopped with `killpg`, a grace
period, then `SIGKILL`; `taskkill /T /F` where `killpg` does not exist. `shares_our_group()` guards
the one way that goes badly wrong: where the child shares this process's group, signalling it would
kill the caller, so the narrow kill is taken and the teardown reports itself **unconfirmed** rather
than implying a clean stop. Consequently **an interrupted run makes no tree comparison at all** —
`treeMutated` is `None` with a basis naming the race, the same refusal `_tree_stamp.porcelain`
already makes for a tree git will not describe.

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

**`--also <phase,...>` is a group's one run.** Phases built on one combined branch share one tree,
and a group sign-off runs the phase gate once, for the member whose `testGate` holds the union.
Owned by that member's files alone, the run reported a rewrite of a file only another member
declares beside a pass. `--also` makes the run own the union of every named member's files
(`group_owned_files`), so the `GATE MUTATED THE TREE` refusal, the coverage answer and the
`scopeDigest` all cover the group. It is additive — absent, the run is what it was — refused beside
`--task`, and a member the plan does not carry is refused rather than skipped. `audit-task.py
signoff` compares that `scopeDigest` against the members' files as they stand when it records a
`passed` verdict, which is how the verdict knows the run it rests on is current.

**A selection miss is asked of pinned paths, and its remedy runs as printed.** The `--full` path
hands its steps to `_evidence_io.selection_miss`, which pins each suite the runner named with
`pin_suite` before asking whether a derived gate listed it; a name that pins to no tracked path,
or to several, prints `SELECTION MISS not asked of <name>: <why>` and is never counted as
listed. The whole ledger read goes in, lost lines included (`unreadable_names`): a file read with
losses may hold the bounding run, so no miss is asked and the `SELECTION MISS not asked:` line
names the file. `_miss_remedy` prints each command as `python3 <audit-task.py> … <manifest>
--project-dir <project>`, the script resolved by `_loader.script_path` and every path absolute and
shell-quoted, so it runs from any directory; the suite in it is the pinned path.

**Withheld mutes.** `withheld_mutes(manifest, task_id)` names the bugs whose mutes a run may not
honour, and `mute_decision` refuses each such entry with that sentence as its `why`, whatever its
`until`: the bug whose `taskId` is the task under `--task` — a mute inside its own fix task's gate
would hide the failure the fix must be seen to clear — and any bug closed by its effective status
(`_manifest_io.effective_bug_status` in `_status_facts.CLOSED_BUG`), whose quarantine is over.
The full run passes no task, so only the closed-bug rule applies there.

**The project is the manifest's.** Without `--project-dir`, the project is
`_panel_write.project_of_manifest(manifest)`, the answer `full-gate.py`, `import-evidence.py` and
`audit-task.py` read, never a count of directories up from the file — that count is right only for
`<T>/docs/audit/<file>` and would record anywhere else into a ledger outside the project.

### `plugins/audit/scripts/governance/record-outside-run.py`
`record-outside-run.py <manifest> --label TEXT --started <ISO> [--ended <ISO> | --duration-ms N]
[--status passed|failed]` — **record a test suite that ran where this plugin could not see it.**

**Why it exists.** `run-test-gate.py` records the runs it *makes*, and for a long time those were
the only runs the ledger knew about. A suite can run elsewhere on the same machine in the same
minutes — a pre-push hook fires one on `git push`, a developer starts one in a second terminal, a
commit hook runs one — taking the same cores, the same ports and the same scratch directories. A
red that a concurrent outside suite had caused was recorded, rendered and read as the gate's own
verdict on the work. Writing this row does not make the red go away; it gives
`_evidence_io.attribution_of` a **named rival with its own row**, so the verdict comes back
`CONTESTED` instead of being claimed alone.

**It is declared, never sniffed.** Guessing an outside suite from the spelling of a Bash command
— does it say `playwright`, does it say `push` — is the read-the-command's-spelling class this
product keeps being repaired for, and it would be wrong in both directions on the first project
that wraps its own runner. So the row is written by whoever knows: the operator, or the hook they
wire it into.

**The row has no subject, and that is the bound.** A gate row carries a `scope` and a task or
phase id, and those are what `latest_by_subject` and `reusable_run` key on. This row's scope is
its own word (`outside`) and it carries no ids, so it can never be pointed at a task, never stand
in for a measurement the plugin owes, and never be repeated instead of a gate. It is a fact about
the **machine in a window**. `--status` is optional and written through as given: absent means
nobody said what the outside suite answered, which is true and better than a word invented to
fill the field. The window is the whole value of the row, so a `--started` that will not parse is
a refusal rather than a guess — and the stamp is read by `_evidence_io`'s own reader, because a
writer parsing instants its own way would disagree with the module that decides whether two of
them overlap, by a time zone.

### `plugins/audit/scripts/governance/import-evidence.py`
`import-evidence.py <manifest> <shard.jsonl> [--json] [--project-dir DIR]` — **bring a CI build's
own evidence ledger file into this checkout, whole.**

**Why it exists.** A CI runner's gate run writes its evidence row on the runner, and that file
never reaches a clone through `git` — it is gitignored scratch unless something copies it out. A
hand copy verifies nothing: a byte changed in transit, a line torn by a truncated artifact
download, a shard typed over another writer's file under the same name, none of it visible before
the row was trusted.

**Verification is borrowed, never re-derived.** Before anything is copied, every line must parse
and `_evidence_io.verify_rows` must hold over the whole file — the same chain check
`audit-journal.py` and the doctor already trust, so a second implementation here could never come
to disagree with it about what tampering looks like. A torn last line is checked separately,
because a truncated tail never becomes a row for `verify_rows` to grade at all.

**A name collision is graded by bytes, not merged.** A file already sitting under the shard's
basename is compared byte for byte: identical bytes is the same import arriving twice and exits 0
as "already imported"; different bytes is refused outright, because the chain's genesis is seeded
from the basename alone (`_journal_io.genesis_prev`) — two different chains sharing one name is
exactly the substitution that seed exists to catch. The copy itself is atomic: the bytes land in a
temp file inside the destination directory and only `os.replace` gives it the final name.

**One run, one row — checked before anything is written.** Every reader of the evidence directory
counts rows, so a run arriving twice is counted twice. The import is refused, exit 1, naming each
duplicated `runId` and the file already holding it, when the shard carries a `runId` the ledger
already holds under another file, or repeats a `runId` among its own rows (the shard itself is
then the holder). The holders come from `_evidence_io.read_rows`'s `rowFiles`, the same read every
consumer trusts. A ledger that cannot be read in full refuses the import too, saying the check
could not be made rather than reading as empty — an unread row may be the duplicate — and names the
file with the step that clears each cause it cannot tell apart — make a file that would not open
readable; truncate a torn tail's partial line on purpose; restore a file with a corrupted line from
its committed copy or remove that line on purpose — and points at `audit-journal.py verify`, which
names the cause. The byte-identical re-import is compared before this check and still reads as
already imported.

**A red full row prints the command that learns from it.** After a successful import — a fresh
copy or the byte-identical repeat — `learn_from_commands` builds, from the rows this import already
parsed, `python3 <full-gate.py> <manifest> --learn-from <runId> --project-dir <dir>` for each
row that is full scope and red by `_evidence_io.row_is_red`. Every path in it is absolute and
shell-quoted — the script resolved by `_loader.script_path`, the manifest argument made absolute,
the project this import resolved — so the line runs as printed from any directory; `render` prints each after the authentication note and `--json` carries them as
`learnFrom`. They are printed, never run: bringing a file in whole is not consent to write the
plan, and a green row prints none.

**The project is the manifest's.** `resolve_project` takes it from
`_panel_write.project_of_manifest` when `--project-dir` is absent — the nearest ancestor holding
`.claude/` or `.git`, else `<T>` for `<T>/docs/audit/<file>`, else the manifest's own directory —
and never from the directory the command was typed in, which would land the shard in a ledger the
plan never reads and print a `--learn-from` command pairing that plan with the wrong ledger. With
`--project-dir`, a manifest that does not sit under it (both resolved through symlinks) is
refused, exit 2.

**What it does not prove.** A ledger is evidence, not authentication — a new shard starts at its
own genesis the moment somebody names a file that way, so a verified chain says the rows were not
edited after the file was written and says nothing about who wrote it. The report says so on every
successful import; the commit that carries the imported file into the repository is the
authorship trail.

### `plugins/audit/scripts/governance/full-gate.py`
`full-gate.py <manifest> [--writer NAME] [--project-dir DIR]`, or
`full-gate.py <manifest> --learn-from RUNID [--project-dir DIR]` — **the one command of the third
place**, meant for a pre-push hook or a CI step that should not have to spell out
`run-test-gate.py --full --record` and its own refusals itself.

**Delegation, not re-implementation.** An entry point may not import another entry point, so
this resolves `run-test-gate.py` by basename (`_loader.script_path`, never loaded — see
`render-report._bench_fixture` for the same shape) and runs it as a **subprocess**, streaming its
combined output line by line and exiting with its **unchanged** code. Nothing here re-derives
what a green or a red full run means; that verdict is `run-test-gate.py`'s alone.

**The one branch this file decides for itself.** `run-test-gate.py --full` refuses (exit 2) a
plan with no `meta.fullGate` — a usage error for a phase-scope caller asking for a run with
nothing to run. A pre-push hook is not that caller: a plan that never declared a third place must
not block every push, forever, over a gate nobody asked for. So this file reads `meta.fullGate`
itself, before invoking anything, and answers with the sentence and **exit 0** instead of letting
that usage refusal reach an operator's shell as a blocked push.

**A red run is learned from, and still blocks.** After a non-zero exit this file reads the row
the run recorded (`_evidence_io.row_by_run`, with the id off the runner's own `evidence: recorded`
line; with no such line, the newest full row stamped since it started the run — never an earlier
run at the same head) and files what it taught through `audit-task.py`, as subprocesses: a
`couple` and a `bug-add` per `selectionMiss` entry, and a `couple --caught` per suite the plan
already coupled that the runner named failing — pinned by `_evidence_io.resolve_named`, so a name
that fits several coupled suites credits none of them. A suite the row lists in its own
`selectionMiss` is never that row's catch: the row says no derived gate ran it, so a coupling
the row creates or widens, or one another row with the same miss taught, is not credited by it —
in either order, which is what makes a second pass over the same row file nothing new. Each verb's own output and exit code are printed;
the exit stays the runner's. It never acts on a green run, on a run the runner said it did not
record, or on a failure the runner did not **name** (every miss is re-asked of
`_evidence_io.named_failing_suites`, which also skips a muted step). The couplings a catch is
credited to are read before any verb here writes, so a suite this run coupled is not also
credited with a catch by it. A miss whose `sources` the row cut (`sourcesDropped`) is
**not** coupled — coupling a suite to a prefix of what it depends on narrows it silently — and
the bug it files says so and points at the tasks' files in the plan. A miss an open bug already
tracks, or a coupling that already covers every source, is not filed again, so a push retried on
the same red does not multiply bugs.

**A miss is filed under its pinned path.** `learning_plan` pins each miss's spelling with
`_evidence_io.pin_suite` over one `suite_listing` of the project, so `couple --test` and
`bug-add --files` name a file the plan can open and the existing-coupling check reads the key the
plan holds. A spelling that pins to no tracked path, or to several, still files its bug — the
failure happened — with no `--files`, no coupling, and a note saying why. Whether a miss is one the
runner named is `same_suite`, never a suffix, and whether the row lists a coupled suite as its own
miss is `own_miss`, the reading `couple --caught` refuses by.

**The project is the manifest's, and a lost file is named.** Without `--project-dir` the project
is `_panel_write.project_of_manifest(manifest)` — the plugin's one answer, never a count of
directories up from the file — and it is always handed to `run-test-gate.py` as `--project-dir`,
so the runner records into the very ledger the red branch then reads. When the run's row is not
among the readable rows and `read_rows` could not read some ledger file in full, `find_row` says
so, naming the file (`_evidence_io.unreadable_names`) with the `--learn-from` command to ask again
once it is repaired, rather than calling the run absent.

**`--learn-from <runId>` learns from a run recorded elsewhere, running nothing.**
`full-gate.py <manifest> --learn-from RUNID [--project-dir DIR]` is the door for a red full run a
CI build recorded into its own shard: learning inside the pipeline would write into a checkout the
build throws away, so the row teaches once `import-evidence.py` has brought it into a checkout
that keeps what is filed. It reads the row with `_evidence_io.row_by_run` and hands it to
`learn_from_row`, the one function the red branch also calls, so the rules above are stated once.
`row_refusal` refuses a row that is not full scope and a row `_evidence_io.row_is_red` calls
green — the one home of the runner's own reading, since `run-test-gate.py` exits 0 exactly when
`status` is `passed`, and the reading `import-evidence.py` uses too — and a run id the readable rows lack
is refused naming each ledger file `read_rows` could not read in full, the way `audit-task.py`'s
`--basis-run` lookup does. Every refusal is one `[full-gate] cannot learn from run …` line and exit
1. Unlike the red branch there is no runner's verdict to keep, so a failed verb or a raise is exit
1 too; exit 0 means the learning ran, and when it filed nothing the lines above the summary say
why. Learning twice files nothing new, by the own-miss rule above. Beside `--writer` it is a usage error, exit 2: a learning pass records no row for a
writer to name.

### `plugins/audit/scripts/governance/drive-phase.py`
`drive-phase.py next <phaseId|taskId> [manifest] [--project-dir DIR] [--answer OPTION] [--reason TEXT]
[--fix FINDING[,FINDING]] [--verbose]` — **the step driver.** One `next` reads the plan and the filed returns, performs
every step of the phase's run that is due and needs no judgement, and prints exactly one
instruction: `dispatch` (an agent type, the task, its model and the brief file `audit-lookup.py
brief` wrote), `decide` (a named decision with its options), or `done`. The command body is the
loop — run `next`, do what it prints, run `next` again — so a task costs the main loop four
requests: dispatch the executor, `next`, dispatch the reviewer, `next`. `dp2` in
`plugins/audit/tests/test_drive_phase.py` counts them over a drive of a fixture plan.

**Every step is an existing verb, run as a subprocess.** An entry point may not import another,
so each verb is resolved by basename through `_loader.script_path` and run: `audit-lock.py
acquire` on every `next` (and `release` at `done`, only when this driver took the lock rather
than being handed it), `audit-task.py start`, `audit-lookup.py brief --role`, `run-test-gate.py
--task --record`, `stamp-verification.py compare --json`, `audit-task.py finding --findings-file -`
for a reviewer's findings, `commit-task-work.py`, and `audit-task.py done --from-return`. A verb
that exits non-zero stops the drive: the driver names the verb and prints its own words whole —
the refusal and the remedy it gives — and exits 1 (`relay_refusal`). Nothing here re-decides
what a verb decides.

**The recorded gate stays before the reviewer.** The gate is recorded and the executor's stamp
graded in the `next` that writes the reviewer's brief, so the reviewer reads the driver's run
instead of making its own. A stale stamp prints the fields that moved (`moved_fields`, off the
comparison's own `fields`), so nothing is left for the model to look up; a comparison git could
not answer says so and never reads as unchanged.

**A task id drives that one task.** `next <taskId>` (`drive_task`) starts it when it is
pending, advances it through the same steps, and prints `done <taskId>` once it is terminal
(`finish_task`, which says `already` when this call closed nothing), leaving its siblings and the
phase's sign-off alone - the run `/audit:run` and `/audit:next` make. A `blocked` task stops it
with its recorded reason and the rule for it; a decision pending about another task in the
phase's drive stops it too, naming the phase drive that answers it. The `dt` cases drive it.

**One task at a time, in id order.** `next_task` takes the task in progress, else the first
ready one. A recorded gate run while sibling executors edit the same tree measures their
unfinished work, so the driver never has two tasks between dispatch and gate at once.

**What the driver keeps.** `stateDir/drive/<phaseId>.json` holds what no verb records: which
brief it handed out for which start (so an agent that filed nothing becomes a decision, never a
silent second dispatch), whether it took the phase lock, the findings it already filed, and the
decision it waits on. A decision is printed again on every `next` until `--answer` gives one of
its options; an option it does not offer, or one that records a reason given none, is exit 2.
`DECISIONS` lists them: a red recorded gate, an agent that filed no return, a high-risk commit, a
commit with nothing in it, a reviewer answer only a human settles, a phase with no ready task,
and the decisions sign-off adds, below.

**Sign-off is the same loop.** When every task is terminal, `sign_off` takes over from `finish`.
The phase reviewer is dispatched (`dispatch_phase_review`, with the brief `audit-lookup.py brief
--role phase` wrote and the head that brief names kept in the state) when a review skill
resolves for the phase or a task is owed its answers there (`review_due`); the reviewer files
through `submit <phaseId> --head`. The `next` after it reads that filed return, records every
finding in one `audit-task.py finding --findings-file -` call (`record_findings`), and prints one
`decide triage`: each finding no fix task names yet, with its options, and what a fix task is
predicted to cost - `FIX_TASK_PREDICTED`, with `FIX_TASK_PRICE_BASIS` printed beside it, which
says it is a benchmark prediction and never a measurement of the project. Each line of that print
stays inside `TRIAGE_LINE_BYTES`. **The review's answers reach a human there too**
(`human_answers`, which is `_filed_returns.needs_human` - the predicate `audit-task.py signoff`
refuses over as well, so the verb run by hand stops where the triage does): every task entry of a filed phase return answering `diverges` or `cannot-tell`,
grading red-first `not-proved` or inherited tests `flagged`, and a phase intent of `diverges` or
`cannot-tell`, is an `[accept]` line, and `sign-off` is refused (`triage_refusal`) until `--answer
accept --reason` settles them - the reason is kept in the summary - or `--answer decline --reason`
hands the phase back to the work (`decline_answer`). A review filed at the marked
head while a task added since is owed its answers is dispatched again (`owed_tasks`), and a
recorded fix task closed at a commit the head does not hold (`fixes_after`) is listed as
unreviewed, with `--answer re-review` beside a `sign-off` whose summary then names it. `--answer fix --fix <id>` adds a task per finding
through `audit-task.py add --fixes` (`add_fix_tasks`), which the drive runs like any other - under
`review.perTask: phase` closed `not-asked` with a basis saying its own diff is unreviewed, the
answer the landing takes from a recorded fix task - and the triage is printed again. `--answer sign-off --reason
<summary>` runs the rest as one step (`signoff_step`): the phase gate (`derive-phase-gate.py`
first when `meta.phaseGate.mode` is set, then `run-test-gate.py --record`), `verify-invariants.py`,
`audit-task.py signoff --verdict passed`, the commit (`commit-audit-state.py`, and
`commit-manifest-index.py` in a sharded plan), the landing (`close-phase.py`, skipped for a phase
that records no branch), and the lock release. **A red phase gate stops before the sign-off verb**
(`red_gate_stop`): the invariants still run and are printed beside it, with the fix-task command
carrying the run's id for `--failing-from`, and the next `next` prints the triage again. Sign-off's other
decisions are a phase reviewer that filed nothing (`redispatch`), a runtime boot owed when
`meta.runtimeBoot` is set and the phase touched its `appRootPath` (`runtime_boot_root`; `booted`
or `not-reachable`, each with a reason, asked before the gate runs), a green phase gate that
printed `NO OVERLAP` or `TREE CHANGED` (`gate_banners`; `accept`), an invariant breach
(`accept`), and a parent that moved (`no-ff`, or `leave` with a reason, the rule printed under
it forbidding a rebase). The boot, the banner and the breach also take `decline` with a reason
(`decline_answer`): the words are kept, the decision is dropped, the green gate it was asked
over is no longer reused, and the drive goes back to any task still open or stops naming how
to add one. A `booted` and an `accept` of a breach are bound to the HEAD they were given at
(`bind_at`, `held_at`), so a commit after them asks again; an `accept` of a banner is bound to the
run it was shown - the HEAD, the held run's id and the gate the phase declares
(`bind_coverage`, `coverage_held`) - so a gate retargeted, or measured again over an edited tree,
at the same HEAD asks again, and the summary keeps the words only while they answer the run the
verdict stands on (`gr4`-`gr4c`); a green phase gate recorded
at the same HEAD is reused rather than run again (`green_phase_gate`) only while the sign-off
verb would still bind it (`held_gate_binds`, which asks `_verdict_binding.phase_binding` and
reuses only the run that is the newest verdict), and a refusal after the gate drops it
(`drop_held_gate`), so a gate retargeted, a declared file edited or a run recorded by hand at
the same HEAD measures again rather than looping; the `gr` cases hold it. A per-task reviewer's
`diverges` or `cannot-tell` under `always` or `signals` is `decide review-answer`, whose
`continue` takes `--reason`, and whose printed rule says to ask the human and pass their words
verbatim (`ct1r`). With no phase review marked in the state, sign-off reads a phase return already
filed at the current head (`filed_at_head`) rather than paying for a review whose return
`file-return` would refuse at that head (`rr1`, `rr2`), and marks its findings recorded only where
the plan's review already holds each of them (`findings_held`), since `finding` appends rather than
deduplicates (`rr3`, `rr4`). Every reason still held, a `continue`'s included, is kept in the
summary (`signoff_summary`). The `sg` cases
drive it over the fixture plan: sign-off's model-facing steps are the review's dispatch, the
triage and the final step, a red phase gate never reaches `signoff`, and several findings are one
`finding` call - each beside a mutant driver that breaks it.

**Where the text and the seams are.** Every line the model is shown is rendered from `STEPS`,
one entry per step, whose `rule` lines print under its instruction when it has any. **That is
where a followed rule lives now**: no pipeline command makes the main loop read reference prose
first (`tools/measure-context.py --gate`), so the rule a step needs - the dispatch's description,
the high-risk confirmation, which answer to a red gate spends an attempt, the sign-off order and
its reason, a held lock, what to do with any other stop - is printed at that step, and
`_refs.followed_anchor_drift()` holds that every step the README's followed table names is here
with a rule. A red gate offers `rerun` beside `retry` and `block`: `rerun` measures again without
re-starting the task, so a gate that could not run spends no attempt; `block` runs
`commit-audit-state.py` after the block verb (`keep_record`), since a blocked task gets no task
commit to carry the rows its gate wrote, and a blocked task's stop and a stalled phase both print
each blocked task's own remedy (`blocked_remedy`): `start <id>` while it has attempts left,
`unblock <id> --reason` once they are spent (`attempts_spent`). A task gate's banners ride its did-line
(`gate P1.1 green (NO OVERLAP)`), and a high-risk task a `risk.confirmed` journal row of this
phase names (`confirmed_in_advance`) commits without the decision, its did-line saying so. A print whose call closed, blocked or signed off an item
carrying an `ado` link, on a plan whose board takes the echo, adds `ado echo owed: <ids>`
(`ado_echo_lines`) - no verb sends the board update, so the instruction is the whole of it. `reviewer_due` is the one place the
per-task reviewer's dispatch is decided. `did_tasks` reads the driver's own did-line back, and
`did_events` adds the words for a fix task added, the sign-off, the landing and the lock release
(`FIX_ADDED`, `SIGNED`, `LANDED`, `RELEASED`); `tools/stream-cost.py` reads a driver session's
task cycle, fix-task and close spans from them, since those steps run in subprocesses the
session's stream never shows.

**Bounded output.** Every print that is not a stop stays inside `INSTRUCTION_BYTES`; `dp3` holds
it over the fixture drive, and `--verbose` adds each verb's run above the instruction. The brief
path is printed from the project root when it lies inside it (`project_relative`), so the size of
a print does not grow with where the project sits on disk.

**`submit` is an agent's last act.** `drive-phase.py submit <taskId|phaseId> --role
executor|reviewer [--head SHA] [--case ...] [--introduces ...] [--deps-from DIR]
[-- <test command>]` reads the return on stdin and runs, in order, what the agent prompts used
to explain step by step: the shape check (`submitted_shape`, with the fields `submit` fills set
aside, so a malformed return costs no red run and writes nothing); for an executor whose return
is already filed for this start, a refusal before anything runs (`already_filed`); with a test
command, `stamp-verification.py red --json`, whose `redFirst` block replaces the agent's - owed
on a `tdd` task, which is refused without one, and a test that passes without the fix gets no
block and no filing (`red_block`); then `stamp-verification.py take --json`, after the red run
because the stamp is taken after the last claim, refused as a missing stamp when it prints no
`audit-stamp:` line or git put no HEAD in it (`take_stamp`); and last `audit-task.py
file-return`, the write-once door, which a reviewer's return and a phase review's (`--head`)
reach unchanged. Exit 0 filed, 1 refused with nothing written, 2 a usage error. The `ds` cases
in `plugins/audit/tests/test_drive_phase.py` hold each refusal beside the twin that files, and
the drive's own cases play every agent through `submit`.

### `plugins/audit/scripts/governance/propose-gates.py`
A plan proposal that reads what previous runs in THIS repository actually ran and what they
caught, instead of the tree alone — the waste `/audit:init`'s recon step pays everywhere except
a repository with no history, where reading the tree is the right first guess. Folds
`_evidence_io.command_tally` (the same tally `_doctor_trail.check_gate_patterns` reads) into one
of four claims per candidate command: `tree` (nothing has ever run under that exact spelling —
the confident failure mode this exists against: a repo with no recorded run must say so, not
propose in silence), `insufficient` (some history, thinner than `_evidence_io.MIN_HISTORY_RUNS`
supports a verdict from), `never-failed` (past the floor, no failure — a candidate for removal)
or `catches-things` (past the floor, has failed — a candidate for every plan). `historyAvailable`
is the repo-wide flag stated once rather than left for a reader to re-derive from every entry,
but the basis is still per-command: a candidate this repo has never run under any spelling reads
`tree` even in a project full of history for other commands. Read-only, exit 0/2. Layer 7 (reaches
`_evidence_io` at layer 2 and nothing else). `--selftest`.

### `plugins/audit/scripts/governance/record-risk-confirmation.py`
`record-risk-confirmation.py <manifest> <phaseId> --confirm-high-risk "<their words>"` —
**the human's answer to `orchestrator.md` step 4a, given before the run instead of during it.**
`--project` names the directory holding `.claude/` and the journal, `--json` prints the answer.
Exit 0 recorded, 1 NOT recorded (the journal is off, or the append did not land), 2 usage —
including a phase with no open high-risk task.

**The gap it closes, and it is a reported one.** Step 4a stops and asks a human before a
`risk: "high"` task's commit, always. An operator running the pipeline unattended has nobody to
ask: asking parks the run for hours, so the run instruction itself gets treated as the
confirmation and the report says so afterwards. The rule as written offers a stall or a quiet
override, and a quiet override of a safety rule is the worse of the two. The third option is to
let the answer be given **early and recorded** — `always ask` stays true, and the trail says who
answered and in what words.

**What makes it safe rather than merely convenient is the bounding, and the bounding is here.**
`covered_tasks()` computes the set the answer may cover — *the phase the operator named*, *risk
`high`*, *open work only* — from the manifest as it stands at that moment, and the `risk.confirmed`
row records those ids. A confirmation phrased as a condition ("any high-risk task in this phase")
would go on answering for work that did not exist when it was given, which is not an answer: it is
the rule deleted with a flag left where the rule used to be. So a task that becomes high-risk
afterwards — retargeted, or added mid-run — is absent from the list and is unanswered, and step 4a
stops and asks for it exactly as before. A phase with no open high-risk task is **refused**, not
recorded as an empty row, because a confirmation with no subject is a standing permission.

**It fails loud, which is the opposite of `close-phase.record_row`'s contract and deliberately
so.** There the merge had already happened and a failed append must not report it as not having
happened; here the row *is* the whole deliverable, so `journal.enabled: false` and a failed append
are both exit 1 saying the confirmation was NOT recorded — the run then has no pre-given answer and
goes back to asking per task.

**What no mechanism here does:** gate the commit. Nothing refuses a commit of a high-risk task
missing from the list; the orchestrator obeying step 4a is what does that, and step 4a says so in
its own sentence. This command bounds what may be **claimed** and leaves a row a reader holds the
claim against afterwards (`audit-journal.py show --target <phaseId>`).
**Those three fields now live in `_tree_stamp.py`, not here.** They were written for this file and
are still what this file records; what moved them down is that the same fingerprint is needed for a
claim carried in *prose*, and a second expression of "which tree was this" would **be** a second
tree identity. The module holds `porcelain()`, `HEAD_BASIS`, `scope_digest()`, `dirty_digest()` and
`tested_state()` unchanged. An entry point reaching another entry point is the `KNOWN_LAYER_DEBT`
shape that table exists to keep rare, which is why the shared half came down to L2 rather than the
new command reaching up.

### `plugins/audit/scripts/governance/_verdict_binding.py`
Whether a recorded gate verdict binds the declared work as it stands now - one answer for every
writer that stands on one. `commit-task-work.py` commits a task's work only under a green run of
the gate that measures it; `audit-task.py signoff` records a `passed` sign-off only under a green
run of the phase's gate (a group's carrier, over every member's files); `audit-task.py done` and
`close-phase.py` close a task or land a phase only while its newest verdict still holds. A second implementation
of the rule in the sign-off verb had fewer arms than the task commit's: it graded a repeated
verdict by the repeat's own empty stamp and refused it on an unchanged tree, compared a digest the
recorder took with its own writes left out against one taken with them in, and accepted an
`empty-gate` row under a gate that had since gained entries. So the rule moved here, at L3 - the
first layer above `_evidence_io` (the ledger) and `_tree_stamp` (the digest), which are peers and
cannot hold it. `binding()` takes the subject's ids, the gate entries that measure it and their
source, its declared files and the caller's own sentences, and answers `bound`, `no-gate` or
`refused` with a sentence naming the run: the newest row for the subject, never the plan's
pointer; a repeat graded through `reusedFrom`; a gate changed after the run; a red nothing
retired; an unparseable line that could be the subject's; the digest with the recorder's paths
left out on both sides. Every refusal carries the `arm` that produced it, and a close reads the
arm rather than the sentence: `close_refusal()` refuses a close on every arm in
`CLOSE_REFUSING_ARMS`, whose comments give each arm's reason - every refusing arm except no run
recorded and an `empty-gate` answer, where there is no measurement to vouch for and the sign-off
recorded why. `group_of()` answers which run grades a phase signed off in a group: the carrier's,
over every member's files; `member_red()` refuses a member whose own rows hold a red newer than
that run. `binding()` takes the ledger as `ledger_texts()`-shaped sources and the
tree to digest, so a landing reads the head it would merge rather than whatever tree `--project`
names - `rows_of()` is the union of two copies of one ledger by row identity, and an unreadable
source is unreadable, never no run. A sign-off recorded with `--no-evidence-reason` is honoured
by `close_refusal()`: the `STALE_GREEN_ARMS` do not refuse, and a red refuses only when recorded
after the sign-off's `phase.verdict` journal row (`signoff_moment()`), or always when that row
cannot be found. The way past a refusal is `--override-verdict`, journaled as
`audit.verdict.close-overridden` naming the run and the reason, and refused when the journal is
off or the row will not write. The digest reads
the declared files' content and nothing wider: a gate row records no content digest of undeclared
paths, which is the stamp's `content` field alone. Its cases are
`plugins/audit/tests/test__verdict_binding.py`.

### `plugins/audit/scripts/governance/_tree_stamp.py`
Which tree was this, and is it still that one.

The first half is `run-test-gate.py`'s three identity fields, moved (above). The second half is the
question that file never had to ask: **given a stamp taken earlier, is the tree still the one it
names?** `take()` reads the tree once and returns both the machine token and the full basis, so the
line a reader is shown and the line they paste cannot describe different moments. `compare()` grades
a stamp against the tree now.

**Three answers, not two.** `current`, `stale`, and `unestablished` — git could not answer, so
nothing was graded. That third word is this tree's existing vocabulary (`porcelain()`'s `None`,
`_doctor_trail.running_plugin_verdict`, `_evidence_io`'s null check count): a question that could
not be asked must never be reported as the comfortable answer. The rule lives in `field_state()`,
where a null on **either** side is `unanswerable` and never `agrees` — `None == None` is True in
Python and false in English, and reading it the Python way is precisely how a directory git cannot
describe comes back reported as a directory that had not changed. `not-declared` is kept apart from
`unanswerable` because their causes differ and so do their repairs: a scope digest is null when the
work declares no files, which the caller chose, and null when git could not read them, which it did
not. **Moved outranks unanswerable** — a tree with one field moved and another unreadable *has*
moved, and reporting that as ungradeable would hide a fact already in hand.

**A stale answer names the field that moved**, with what it was and what it is now. Three fields are
three repairs, and "stale" on its own sends a reader back to re-run everything.

**The scope rides inside the token.** A comparison handed a second file list would silently answer
about a different question, which is the held-model-of-state failure the whole design is against,
reappearing inside the tool built to catch it.

**What a stamp does not establish is printed beside it.** `FIELD_LIMIT` pairs each field with its
basis key and its limit, and the limits are constants rather than docstring sentences *because they
are rendered* — a docstring nobody prints is a second statement of the same limit, free to drift
from the one a reader sees. `DIRTY_LIMIT` is inherited from `dirty_digest()` unsoftened: the digest
records **which** paths were dirty, never their contents, so a rewrite of an already-dirty file
outside the declared scope moves nothing here. `tsl2` exercises that rather than describing it.

### `plugins/audit/scripts/governance/_proc_group.py`
One child process tree run so that it can be stopped whole, and a stop signal turned into an
exception so a caller's `finally` runs. `run-test-gate.py` solved both first - a timed-out
`subprocess.run` kills only the direct child, so a runner's grandchildren kept writing, and
SIGTERM with no handler ends the interpreter without running a `finally` - and
`stamp-verification.py red` met the same two failures, so the answer moved here rather than
being written twice. `group_kwargs` gives the child a session of its own, `tear_down` sends the
group SIGTERM then SIGKILL and says whether that could be confirmed (`shares_our_group` keeps it
from aiming at its own caller), `drain` reads what was written after the group is gone, and
`arm_interrupt`/`disarm_interrupt` install and restore handlers that raise `KeyboardInterrupt`
naming the signal. What it cannot cover is SIGKILL, which no handler sees. Layer 1; its cases are
in `plugins/audit/tests/test__proc_group.py`, and `run-test-gate.py`'s names are this module's
objects.

**It also owns the shell a plan command runs under.** A plan's commands are POSIX shell, and
`shell=True` is `cmd.exe` on Windows, which reads none of `export`, single quotes or `${VAR}`
and still returns an exit code. `locate_sh` resolves in order: `/bin/sh` when it exists, and then
nothing else is asked (the argv is `shell=True`'s own, so a POSIX machine runs every command byte
for byte as before); else the `sh` on PATH; else the `sh.exe` Git for Windows installs beside
`git` — `bin\sh.exe` before `usr\bin\sh.exe` — and never anything under `%SystemRoot%`, whose
`bash.exe` is the WSL launcher. There is no fallback to `cmd.exe` and no bare `sh` left for the
OS to fail on: with no shell, `resolve_sh` and `shell_argv` return `NO_POSIX_SH`, a sentence
naming Git for Windows, which `run-test-gate._shell` turns into a `could-not-run` step (exit 127)
and `derive-phase-gate._spawn` into an observation with no exit and that sentence as its error.
A beside-git shell is started from a native process, so it does not get the PATH a Git Bash
would give it; `locate_sh` returns `<root>\usr\bin` and `<root>\mingw64\bin` with it, and
`shell_env` puts them ahead of the inherited PATH on a copy of the child's environment. A
`/bin/sh` or PATH `sh` gets none, and its child's environment is the caller's own object,
untouched. Both spawn sites take argv and env from ONE call, `shell_invocation`, so the shell and
its PATH cannot drift apart between them. The path module is a parameter throughout, so the
cases judge Windows spellings under `ntpath` on every host.

### `plugins/audit/scripts/governance/_runner_output.py`
Every reading of what a test runner printed: `_SUMMARY_READERS` and `summary_count` for how many
checks a runner's own summary says executed (`None`, never zero, for output no reader recognises),
and `_FAILURE_READERS`, `jest_failures` and `_VITEST_FAIL_LINE` for which checks failed. They were
written in `run-test-gate.py`; `stamp-verification.py red` asks the same output the same questions,
and an entry point may not import another, so they moved here rather than being written twice.
`failing_suites` and its path filters stayed in the gate, because they read `_evidence_io`'s
limits and that module sits above this one. Layer 1; it reaches nothing but `_output`. Its cases
are in `plugins/audit/tests/test__runner_output.py`, and `run-test-gate.py`'s names are this
module's objects.

**It also holds what `red` reads** — `TALLY_READERS`, `CASE_READERS`, `read_tally` and
`failing_cases`, the narrower question of whether a NAMED case failed an ASSERTION. The house
harness, pytest and unittest have tally and case readers of their own there - pytest's is not the
gate's summary row; jest and vitest are read through this module's own summary and failure
readers, each case carrying its `suite` path, its title `chain` and an `assertion` flag. Under
jest the flag is set by the first line under the bullet: a matcher hint
(`expect(received).toBe(expected)`) or the hint jest prints for a `node:assert` call
(`assert(received)`, `assert.strictEqual(received, expected)`), never an `AssertionError` line;
under vitest by chai's `AssertionError`. A thrown exception or a suite that failed to run never
sets it. `read_tally`, `failing_cases` and `jest_failures` strip every terminal escape once, on
entry (`plain_text`), so a run forced into colour (`FORCE_COLOR`) reads as it does without. A suite that failed to run
counts as a failure no case ran, so a run whose only failure is one is a collection error, never a
red. Mocha and playwright have no row: what they print under a failure has not been recorded.
The names `stamp-verification.py` keeps for them are this module's objects.

### `plugins/audit/scripts/governance/stamp-verification.py`
The CLI over it: `take` a stamp, or `compare` one against the tree now — and `red`, which
proves a red-first without touching the tree it is pointed at.

**Why a command and not a helper** — the caller is orchestrator and agent *prose*, which reaches
Python only through Bash, the same reason `verify-invariants.py` and `check-ado-item.py` are
commands. `take` prints every field with its basis and then the one line to carry;
`compare` reads that line out of arbitrary text (a commit message, a report paragraph, an agent's
reply) and grades it.

**Three exit codes for three answers**: `0` current, `1` stale, `3` unestablished, `2` for every
refusal. Sharing `0` would make an ungradeable comparison read as *unchanged*, which is the false
clean sheet the design refuses; sharing `1` would send a reader to re-run work that may be perfectly
current. `EXIT_FOR` is derived from `_tree_stamp`'s own verdict words, so a fourth verdict cannot be
added and left sharing a neighbour's code.

**A stamp that cannot be READ exits 2 and never 0.** Two stamps in one document is a refusal rather
than a choice — picking the first or the last would be the tool guessing which verification the
reader meant, and a wrong guess grades a claim against a tree it was never taken on.

**`--task` takes the declared scope off the plan.** A hand-typed file list beside a manifest is the
same held-model failure one step earlier, so `--manifest M --task T` reads `task.files`; passing
both `--files` and `--task` is refused rather than resolved.

**It is not `/audit:doctor` and does not repeat it.** The doctor already reports that the hooks in
this session are an older installed copy, and what an abandoned worktree left behind — questions
about the *installation*. This asks about the *tree*. A claim taken while the doctor was warning
about a stale copy is a claim whose stamp belongs beside that warning, not instead of it.

**`red` runs the test against code without the fix somewhere other than the shared tree.** The
briefs used to prove a red by undoing the fix in the working tree for the length of the run, which
is a write over ground siblings are editing, and a host refused it beside a sibling's uncommitted
work. `red --manifest M --task T [--deps-from DIR] -- <cmd>` checks HEAD out with `git worktree add --detach` into a
temp directory (hooks pointed nowhere), copies the task's declared **test** files from the working
tree over it — a declared file is a test when `tests.add` names it or its path has a test shape;
the rest stay at HEAD, and the split is printed — runs the command there, and removes the
throwaway in a `finally`, asking git afterwards whether it still lists it. A throwaway it could
not remove is exit `4`, never folded into the verdict. A command naming the shared tree by path is
refused before anything is built, because it would run the shared files and grade the fix.

**The run is one process group, and a stop signal is an exception.** `_proc_group` is the module
`run-test-gate.py` and `red` share: the child starts a session of its own, a timeout or an
interrupt tears the whole group down, and SIGINT/SIGTERM raise so the `finally` runs.
ONE deadline, `--timeout`, starts before anything runs and covers every git call that builds or
reads the throwaway and every run - the task's, the second (`--introduces`), HEAD's own and the fix
run - each getting what the earlier ones left; at most one run
can time out, because each later run is made only when the one before it finished. What follows the
deadline is bounded and summed in `TEARDOWN_MARGIN` - one teardown and the removal's two git
calls, each capped at `REMOVE_GIT_TIMEOUT` - and `--timeout` is refused above `MAX_TIMEOUT`, the
host's limit less that margin, so the helper's own deadline and cleanup finish before the host
kills it. SIGKILL cannot be caught; a throwaway left
that way is reported by name the next time - `leftover_throwaways` reads `git worktree list` for
`THROWAWAY_PREFIX` and grades each by the pid its `OWNER_FILE` records: `running` while that
process lives (a sibling's `red`), `left-behind` once it is gone, `unknown` with no record - and
never pruned. The throwaway's temp directory is never inside the shared tree: `holder_base`
skips a TMPDIR that points there. The child runs with `SCRUBBED_ENV` removed and, by path rather
than by substring, every value that is a path under the shared root - a path list loses only its
entries under the root, so an in-repo `.venv/bin` leaves PATH intact otherwise - and every
`redFirst` basis names what was dropped. A value that is not itself a path but carries one under
the root - an option string such as `NODE_OPTIONS=--require …/setup.js` - is kept, since it is
not a path to rewrite, and named in the basis as `kept, naming the shared root`, because a runner
reads the path inside it. The throwaway holds only tracked files, so `dependency_plan` asks git
for the ignored directories of `--deps-from` (`--project` by default) and `link_dependencies`
links each `node_modules`, at any depth, and each `.venv` whose parent exists at HEAD and which
holds no link into the tree into it
entry by entry, again after every reset; a real directory of links rather than one link to the
whole directory, so a new entry a runner makes there stays in the throwaway, and `.cache`, `.vite`
and `.vite-temp` are never linked. The leaks that link opens are named, not closed: a link or
editable-install path landing in the shared tree outside every dependency directory (a workspace
package) would let HEAD's run read the fix, so the directory holding it is not linked - its reason,
naming the entry `workspace_links()` found, joins the skipped list the basis prints - and the run
is made without it: a command that never needed that directory (a unittest run by the system
python beside an in-repo `.venv`) still proves, and one that did fails for want of it. The scan
lists only top-level and `@scope` entries and the `.pth` and `__editable__` files directly under a
site-packages directory, and stops at the deadline; a write a runner makes INTO a linked entry lands in the
source checkout and nothing watches it; and the user's `~/.npmrc` and an untracked project one
never reach the run's fresh home (a tracked one arrives with HEAD), with `NPM_CONFIG_USERCONFIG`
dropped from the environment. Every basis names what was linked, from where, what was skipped and
what became of each `.npmrc`. Any other untracked dependency (generated files) still cannot run
there and comes back `could-not-prove`; and the throwaway shares the repository's git directory,
so a test that runs git in its own cwd writes shared refs.

**`proved` needs a tally, a named case of the task's own, and an assertion.** `classify_run()`
reads the house harness's line, pytest's summary (framed, or bare under `-q`) or unittest's
`Ran N tests`, and `failing_cases()` names each failing case with whether it failed an assertion,
reading only the lines of the runner whose tally the verdict came from (a passing house case may
print `ERROR: <path>` as the message it asserts on, or echo a whole unittest transcript). When the
output carries the tallies of more than one runner, the command decides if it names one (`pytest`,
`-m unittest`, a house `--selftest`); otherwise the verdict is `mixed-tally`, which prints
`could-not-prove` and names every tally it saw:
a house `FAIL` that is not a build escape or a duplicated id, a pytest `FAILED` whose reason is an
`assert`, a unittest `FAIL:`. A pytest body exception and a unittest `ERROR:` are named but are not
assertions. `proved` needs one of those failures to be the TASK'S OWN, and that is decided by a
GREEN BASELINE, not by reading output (`baseline_problem()`, `fix_problem()`, `own_failures()`):

Every run - HEAD's baseline, the task's run, the `--introduces` second run and the fix run - is made
in the throwaway reset to HEAD (a forced checkout and a clean of untracked and ignored files), with
an isolated environment of its own (`_isolated_env()`): a new empty home under every name a home
lookup reads (`HOME_VARS`, the table `tools/sweep-selftests.py` isolates its children with), a new
TMPDIR/TMP/TEMP, and `PYTHONNOUSERSITE=1`. So the runs differ only in the files laid over the tree.

1. HEAD's baseline runs FIRST, before any file of the task's is laid over or run: HEAD's own test
   files, the same command, HEAD's implementation, with every declared test file new at HEAD laid
   over as an EMPTY file - except a jest or vitest one (`_is_js_test_path()`), which is left ABSENT,
   because both runners fail an empty suite (measured in `stamp-verification.py`'s design note,
   paragraph (3)). It is always made, and the stubs are why no reader of the command's
   arguments is needed: whatever the command reaches - a dotted module name, a shell wrapper, a
   discovery, a file the working tree deleted - the baseline reaches too, minus the new files'
   content. That is more than the task's cases: whatever a new file imports, inherits or loads is
   not reached either, which is why step 4 binds a credit to the task's edit and not to a file. It
   must be GREEN - exit 0 with no failure counted, or an exit 5 whose ONE runner's tally counts no
   case run and no failure (a command naming only new files gives it, and pytest gives it when `-k`
   deselects every case) - or, where a jest or vitest file was left absent, exit 1 with that
   runner's own no-test-file sentence (`No tests found, exiting with code 1`, `No test files found,
   exiting with code 1`) and no tally counting a case or a failure (`_js_none_found()`), its
   counterpart of that exit 5; the words "no tests ran" are never read alone, since a red run followed by
   an empty one prints them too, and the unittest and pytest tallies count every `Ran N` line and
   every summary line - so the fix run of step 3 is judged by all its invocations as well, not by
   its last. Anything else -
   already red, stopped, unreadable - is `could-not-prove` with the instruction to narrow the
   command to the task's cases;
2. the task's run - its test files on HEAD's implementation - is red on an assertion;
3. the fix run - the task's test files on the working tree's implementation - must be green, with no
   fewer cases than the task's run, so every failure turns green;
4. then a failure of step 2 is the task's own - a new case or an edited one - only where the runner
   locates it in ONE declared test file (`case_site()`: a pytest node id's path or unittest `-v`'s
   module, matched by trailing components because both print them relative to their own top
   directory, refused when two declared files match or when an undeclared file in HEAD's tree or
   the throwaway equals or ends with the same path - for a unittest module even on an EXACT match,
   since unittest resolves a module through `sys.path` and `test_old` names whichever `test_old.py`
   came first, while a pytest node id is a real path; the longest module prefix naming a declared
   file, so a nested class keeps its chain; or the one declared script a `__main__` or house run
   executes, spelled `./`, absolute or `-m`), the class the runner names there holds its `def`
   (`_definition()`, read by ast as each name's LAST top-level binding in its body, `_binds()`
   reading only what really binds a name: a Name target through tuples, lists and starred - never
   under an attribute or a subscript, so `New.maxDiff = None` rebinds nothing - an annotated
   assignment with a value, an augmented one, `del`, a `for` target, `with ... as`, a match
   capture, an import (a `*` import counts as binding anything), a def, a class, and a walrus
   anywhere in the statement outside a lambda; any of those after the def means the def is not
   what runs, and so does a later statement at any level of the chain that `_replaces()` the case
   on its class - an assignment of any kind to the exact attribute path `<chain>.<case>`
   (`New.test_x = f` at module level, `Inner.test_x = f` in `Outer`'s body) or a
   `setattr(<chain>, '<case>', ...)` naming it literally - while any other attribute of the class
   is untouched; a def in a string, in another class or merely inherited is not it), and no test file
   anywhere in HEAD's tree (`head_tree()`: `git ls-tree -r` filtered by `_is_test_path()`, read
   by one `git cat-file --batch` under the deadline) holds an ast-identical def under the same
   class chain and name (`credit_problem()`). That is keyed by the definition, not by the path, so
   a case HEAD has is refused wherever it lands - imported, inherited or loaded by a new file,
   carried by a `git mv`, or copied verbatim. A house run carries no definitions, so its one
   script is compared whole instead (`module_key()`): a script whose module ast is identical to
   one of HEAD's test files is HEAD's suite, moved or copied, and is refused. A HEAD case is
   therefore not credited unless the task edited its definition - or, under a house run, the
   script; if HEAD's tree cannot be read no case is credited; a runner that
   locates no failure is `could-not-prove`, with each case's reason; and `--case` must name a
   credited one. That rests on two
   conditions, and holds only while both do: the runs differ only in the files laid over, which the
   reset and the isolated environment provide; and HEAD's cases give the same answer on the same
   files, which the rule cannot check.

`--introduces` requires the same baseline. **What this cannot see**, each a named limit: state
outside the throwaway that a run reaches by an absolute path or through the git directory the
throwaway shares with the repository (config, refs) - HEAD's baseline runs first, so nothing of the
task's can reach it, but the task's run and the fix run could still read what an earlier run wrote
there; network or service state that changes between runs; a flaky or time-dependent HEAD case,
which can fail in the task's run and pass in the baseline and the fix run; and a house suite - its
`FAIL` lines carry no location, so a run of exactly one declared file is credited with every case
that file's run prints, including one it imported from HEAD's tests and ran itself; under pytest
or unittest, a new file that defines a case of the same name as the HEAD case it inherits and calls
the inherited one from it; any edit to a HEAD case's definition, a docstring included, which makes it
the task's case, so an edit that changes nothing the case asserts still lets a new file that reaches
it be credited with HEAD's red; and the other direction - an unchanged HEAD case the task turns red
through something else in its file (a helper, `setUp`, a constant) is not credited, and needs its
definition touched or a case of its own. A copy of a HEAD case under a renamed class or case name is
a new definition and is credited; a HEAD case in a file `_is_test_path()` does not call a test file
is not in the set a copy is compared against; a rebinding inside the block of an `if`, `try`,
loop, `with` or `match` is not read (only what the statement's header binds is); a decorator that
returns a different function than the one it decorates is not read, so a decorated def is taken to
be what runs; a `setattr` whose name is computed rather than a literal, or whose object is reached
some other way than the chain's own dotted names, is not read either; a house suite moved or copied with any edit is compared as a new file and is credited
with every case it prints, HEAD's among them; and a unittest module name, exact or trailing, also
refuses a legitimate case when an unrelated file elsewhere in the tree ends with the same path -
run the file by its path, or under pytest, to prove it.

Seven review rounds each found another way to credit a case past a RED baseline by reading two runs'
output - a relabelled case, a label carrying a per-run value, a quiet stop, a failfast set in the
file, a file the task's run rewrote - so the rule stopped crediting against a red baseline at all
rather than adding an eighth reader. What that costs is stated plainly: a command already red at HEAD
must be narrowed to the task's cases before it can prove anything, and a case whose red the fix does
not turn green is not proved. HEAD's file list is read NUL-separated (`ls-tree -z`), so a declared
test file whose path git would quote is found like any other, and every run is made with
`PYTHONDONTWRITEBYTECODE=1`, so a swapped file of the same size written in the same second cannot be
shadowed by a stale cached bytecode file. The baseline is paid on every run it is owed, the fix run
only when the task's run is red, and the payload records each one's exit and seconds. `--case` narrows to the ids or labels it names and must
name a case that failed an assertion, because the flag is chosen by the party being checked; the
basis names the case and says whether it was named or derived. A house suite whose every failure is a block that raised while being built, a
run with errors and nothing asserted, zero collected, and a bare traceback ending in a compile or
import error are `collection-error`, which prints `could-not-prove` — unless the task
**introduces the symbol**: `--introduces S` needs an identifier, absent from HEAD's copy of every
declared implementation file and present in the working tree's; a final error of the
import/attribute/name class naming `S` whole (pytest's `E   ` gutter is read, and a tally-less
AttributeError counts as a collection error), never a syntax error; and a SECOND run in the
throwaway, with the working tree's implementation copied in, that no longer ends on that error and
reaches its assertions. A runner whose tally it does not read is `no-tally`, also
`could-not-prove`. A green run
gets no word at all (exit `1`): a test that passes without the fix is work left, not an outcome to
record. The block it prints is the executor's own `redFirst` shape, `{status, basis, at}`, and
every word it can print is one the schema's enum declares.

### `plugins/audit/scripts/governance/derive-phase-gate.py`
Observe, derive, record: a PHASE's sign-off gate, computed rather than declared. `_gate_derive.derive()`
is PURE — every observation it needs arrives through a `facts` dict, and it never shells out or
reads git — so this is the one caller that gathers those observations for real and hands the
result to `derive()` unchanged. The runner never derives; it only measures what the phase
declares.

**`meta.phaseGate.derived.runner` names a `meta.buildCommands` key** — the test runner this
phase's gate is stated in terms of, carried through only as the DISPLAY label (`entry`) this
file's own lines and `testGateDerived` name, never resolved or run for a listing.
**`meta.phaseGate.derived.spelling` is that runner's own path-scoped RUN command**, carrying a
`{paths}` placeholder — the SECOND shape source `_gate_derive.resolve_shape` tries, read only
when no sibling task's own gate carries a path-scoped entry: the sibling's entry is EVIDENCE the
runner already accepted it, so it wins whenever both exist. `{paths}` is filled by LITERAL
substitution with the shell-quoted, resolved test paths — never through `repointed()`, because
the placeholder is not a path-shaped token that function would recognize. A `spelling` with no
`{paths}` placeholder is ignored, with a printed reason; with neither a sibling nor a usable
`spelling`, the basis is `phase-no-spelling`, unchanged. The printed lines and `testGateDerived
.shapeSource` name WHICH source supplied the shape — the sibling task's id, or the literal
`meta.phaseGate.derived.spelling` — so an operator can go read it. **The two listings
this file actually runs live under `meta.phaseGate.derived.listing`**: `.all` lists every suite
file the runner would collect, with no path filter — the FULL listing — and `.related` carries a
`{paths}` placeholder, filled with the shell-quoted union of the phase's own tasks' `files`, for
the RELATED listing. Both listings write one line of output per path and never execute a test —
a listing that ran a suite would make derivation as expensive as the thing it exists to narrow —
and both are TIMED: `fullListing` and `listing` each carry their own `durationMs` in
`testGateDerived`. Each subprocess runs through `_proc_group`, the same module `run-test-gate.py`
and `stamp-verification.py red` share, so a listing that hangs is torn down whole rather than left
running past this process's own patience.

**`meta.phaseGate.mode` ABSENT means no derivation was ever asked for** — this prints why and
writes nothing, exit 0, before a single subprocess runs.

**A `verifiedOn.command` that cannot be run or exits non-zero is its own printed skip reason**
("the version command failed"), kept apart from a machine answering a DIFFERENT version:
folding the first into the second would render as "this machine answers `None`", which reads as
an actual mismatched answer rather than as no answer at all having been produced.

**`derived-empty` IS reachable from this runner, from TWO triggers, and `_gate_derive.derive()` is
the ONLY place either is computed.** `meta.phaseGate.derived.listing.all` is the first: an ALL
listing free to run, exit 0 and name no suite (a sibling-sourced shape can never return an empty
`test_paths`, so this is what makes the basis reachable at all) — caught before coupling,
importers, changed or last-failed ever run. `meta.phaseGate.derived.spelling` is the second: when
the shape came from THAT source and, after every arm has had its turn, `test_paths` is still
empty, substituting `{paths}` with nothing would make the gate mean either the WHOLE suite or
NOTHING depending on the runner — so it widens too, with its own reason. Both triggers write the
SAME basis word and the SAME `attribution: None`.

**A THIRD wide basis, an importer listing resolved to the full suite ("DERIVED = FULL"), gets the
SAME treatment** — `attribution` is `None` there too: the `test_paths` `derive()` had accumulated
before deciding the importer listing equalled the full one is real, but it is not what the wide
gate runs, so a caller reporting it as a per-arm breakdown would be printing a narrowed-looking
count for a gate that is not narrowed. **This file's renderers
(`_render_lines`/`_brief_line`/`_testgatederived`) are keyed off `result["narrowed"]` and
`result["basis"]` — never off whether `result["attribution"]` happens to be `None`**, because a
second, independent computation of the same arms does not know every widening trigger `derive()`
knows, and would report a narrowed-looking breakdown for a gate that is actually wide the next
time one is added — which is why that second computation, `_breakdown()`, calling `_gate_derive`'s
own arm helpers a SECOND time by hand to answer a question `derive()` already had the answer to,
is deleted; `attribution` is the only breakdown this plugin computes. The full-suite case's own
human line is the SAME honest "nothing to narrow to" headline the other two wide bases print,
with `DERIVED = FULL` and the MEASURED listed-of-full pair (read straight from `facts`, never from
`attribution`) as advisories — never a fabricated "N test file(s)" count. `testGateDerived.full`
and `--brief`'s listed/full pair are measured the same way, independent of whether `attribution` is
present, so they stay correct for a full-suite resolution even though nothing is attributed. A
RELATED listing that names none while the ALL listing names some is its own printed reason too,
distinct from a silent "nothing to report" — the importers arm contributes nothing, but says why.

**WRITE, under the index lock, snapshot before, validate after, roll back byte for byte on a
finding** — the same four-step shape `set-priority.py` and `audit-task.py` already hold, reached
through `_panel_write` rather than copied, because an entry point may not import another entry
point. `mode == "shadow"` writes `testGateDerived` and `testGateBasis` only, `phase.testGate`
untouched — the wide gate still signs a shadow-mode phase off. `mode == "enforce"` writes all
three. None of the three fields is a `_manifest_io._STUB_KEYS` mirror (`id`, `title`, `status`),
so the write touches only the phase's own shard in the sharded layout (or the one file, in the
single-file layout) and never the index — one journal row, `phase.gateDerived`, names the phase,
the mode, which fields moved and the recorded basis.

**`--brief` prints the reviewer's one-line basis only** — a count of derived vs. full test files,
the coupling count, the smoke verdict, `testGateBasis` and a timestamp — never a path and never
runner output: the full human line (and `--json`'s `lines` array) carries the per-arm breakdown,
`--brief` never does.

### `plugins/audit/scripts/manifest/audit-task.py` (v0.37.0)
The non-interactive `/audit:task add` doer. The command used to dictate the conventions'
15-field new-task template into the model's hands per add — a class of error (a missed field,
a misspelled enum, a fileIndex nobody extended) this script deletes: the command gathers
answers, the script writes them the same way every time. `add "<title>"` allocates the id
under the INDEX lock (`<phaseId>.<n>` over the whole assembled manifest plus parked-proposal
reservations; gaps are never re-minted; off the development branch the id carries the branch
suffix `_id_shape` names, `P2.4-k7m`, so two branches adding to one phase cannot mint the same one), initializes every template field exactly once,
extends `fileIndex` for `--files`, heals a pending phase holding an in_progress task
(v0.37 A4, reused from `_panel_write`), writes through `_manifest_io` with
`_panel_write._write_back`'s footprint (touched shard + index only when fileIndex changed),
re-validates FROM DISK and rolls every written file back byte-for-byte on findings (exit 1),
and appends a `task.add` journal row in-process (the journal-writes hook only sees edit
TOOLS, not `os.replace` — same blindness `_panel_write._journal` covers). `--phase` absent
resolves the single in_progress phase or exits 2 naming the choices; `--skills null` writes
the explicit JSON-null opt-out (v0.37 B1); a held lock prints audit-lock's own message
(exit 3 live / 4 stale, `--takeover` to seize what a human confirmed dead).

**`add-phase "<title>" --outcome "<…>"` is the same discipline one noun up** — the writer
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
is an allow-list that drops an unlisted details key in silence. One row builder now serves every
verb here: `cancel` had its own and passed the whole viewer DICT as `actor.author`, which
`_journal_io` normalises to a null author with `via: unknown`, so every cancel row went in
anonymous and nothing on the row said so.

**`start <taskId>` is the promotion the plan gate reads.** `add` writes `status: "pending"`,
and `hooks/_config.in_progress_task_map` — what `require-plan.py` resolves an allowed path
through — skips every task that is not `in_progress`, its `fileIndex` arm included (that arm
only re-adds paths for ids already in the filtered set). So a task added to a phase that is
already running has its OWN declared `files` denied on the first `Edit`, and the only
promotions were `/audit:run`, which promotes AND spawns, and a hand edit. The verb writes
exactly what `reference/orchestrator.md` → *Execute the task*, step 2 prescribes as an
orchestrator `Edit` — `status`, `startedAt`, `attempts += 1` — through the same lock,
revalidate-from-disk and rollback, with a `task.start` row carrying `changes` and `attempt`.
Widening the map to read `pending` was the other repair and was rejected: the map has three
consumers, so that edit opens every file of every pending task in the running phase at once
and deletes the per-task narrowing the gate's decision order exists for. It is deliberately
NOT idempotent — `attempts` counts spawns, and a call on a running task is the retry step 4
prescribes — and it refuses a terminal task, a phase id, and a start that would pass
`maxAttempts` (the `blocked` transition owes an ADO echo and a human, so it stays the
orchestrator's).

**`done <taskId> --commit <sha>` is `start`'s twin at the other end**, and it exists for the
same reason: the conventions prescribed the close as a pair of hand `Edit`s, which is how one
task's completion went into the phase shard **and** the index, lost the index to a
`git reset --hard`, and turned out never to have been in the shard at all. It writes `status`,
`completedAt`, `commit`, both halves of `outcome` and `verifiedBy` in ONE write with a
`task.done` row. The SHA is required and must be an object id git can be asked about — a
branch name or `HEAD` is refused, a SHA git HAS been asked about and does not know is refused,
and one git could not be asked about at all (no git, a shallow clone) is written and reported
as unverified rather than accused, which is this tree's rule about a claim whose basis is
missing. A task that was never started is refused, because a terminal state laid over a hole
records an attempt nobody made. Closing the last open task does **not** close the phase:
`phase.status` is sign-off's to write, beside the review verdict and the merge stamp.

**A close against a commit reads the reviewer's FILED answer.** Every `done` that passes
`--commit` needs the reviewer's return filed for the task's current start, or `--intent
not-asked` with its basis; a filed answer is the one recorded, and a typed `--intent` that
differs from it, `not-asked` included, is refused, writing nothing. The rule sits in
`_locked_done` (`_close_intent`), so it holds for the plain form as well as `--from-return`;
a `--no-change` close keeps the rule it had. Under `phase`, a recorded fix task closes only
`--intent not-asked` with its basis: the phase review owes it no answer (`_fr.owed_answer`), so a
`deferred` it recorded could never be answered. `done --from-return` also takes the outcome,
`verifiedBy` (from `testsAdded`) and the red-first block — onto `task.redFirst` — from the
executor's filed return, and refuses when that return is not filed for the current start.

**`file-return <taskId> --role executor|reviewer` is the one write a returning agent
makes**, reached through `drive-phase.py submit`. The return arrives as JSON on stdin; the verb checks the shape the role's agent
definition declares (`_filed_returns.return_problems`), takes no path argument and
refuses one that reads as a path, and writes the text verbatim to
`<evidence dir>/returns/<taskId>/<start>.<role>.json`, where `<start>` is the task's current
`startedAt`. The create is exclusive, so a second filing for one task, role and start is
refused and the first stays byte-identical; a re-start re-stamps `startedAt`, so a retry
files beside it. The evidence directory travels in the close commit, so a clone receives the
claim beside the gate row it can be compared with. What it cannot hold: the task id and the
role are the caller's word.

**`scope <taskId>` gives a task the fields creation could not know**, through the same lock,
revalidate-from-disk and rollback: `files`, `--tests-mode`, `--tests-add`, `--gate` /
`--gate-clear`, `--description`, `--risk`, `--blocked-by`, `--depends-on`. It RE-DERIVES
`fileIndex` rather than appending to it, so a path the task no longer claims is released
rather than left pointing at it. It exists because `/audit:sync pull sprint` imports tasks
with no `files` and told the reader to scope them while no verb could — and `fileIndex` is
what the plan gate matches an edit against, so an unscoped phase ran with its central guard
inert. On a task that has already STARTED what is graded is the SHAPE of the change and not
the call: `files` and `tests.add` may gain entries and nothing may lose one, which is the one
change that cannot re-judge what already happened — `_invariants.commit_scope` reads
`task.files` live, so growing the list can only turn a breach into a pass, and the plan gate
reads it forward, so growing it only ever allows an edit it was refusing. That is the recovery
`reference/orchestrator.md` prescribes for a plan-gate refusal, and until the shape rule
replaced a pair of independent signal checks the task the remedy names failed the gate by
construction.

**`retarget <phaseId>` is the same verb one noun up** — a phase's gate, area, desired outcome,
description or title, corrected after `/audit:init` or an ADO pull chose them. The title is
`--rename` rather than `--title` because the positional slot is already called `title` and
carries the phase id, and a rename is refused once the phase is on a branch: `_branch.slugify`
turns the title into the branch's slug, and the readers of that name part company afterwards —
`close-phase.py` and `manage-worktrees.py` prefer the recorded `phase.branch` while
`resolve-branch.py` composes from the title, so a renamed phase in flight has two names and no
reader agreeing on which.

**`seed ["<phase title>"] [manifest]` writes where nothing exists yet** — the one door here that
refuses the OPPOSITE precondition every other verb checks: it declines when a manifest is
already at the path, rather than when one is missing. It writes the smallest manifest that
validates (one phase, one task, template fields exactly once) with no interview and no
exploration, through `_under_lock`'s shared lock/config/release, now parameterized by
`must_exist` so this one call can ask the opposite question the other six do without a second
copy of the door. The gate is `--gate`/`--gate-clear` or an honestly empty `meta.buildCommands`
— never guessed, because nothing in this tree can mechanically tell a real lint command from a
plausible one. `VERB_FLAGS["seed"]` is `("gate", "gate_clear")` alone: it calls `_phase_gate`/
`_task_gate` directly (which read only those two flags) rather than `_build_phase`/`_build_task`
(which read `description`/`outcome`/`area`/`risk`/... off the caller's namespace), because those
reads are attributed to a verb through its call graph regardless of what variable a caller
passes at the site — sharing them would have made `seed` appear, to the suite's own AST-derived
`vf6`, to accept every flag `add`/`add-phase` do.


`signoff <phaseId> --verdict passed|skipped --summary TEXT` records the sign-off a phase's
derived `done` reads (`_manifest_io.effective_phase_status`): `review.status`, `review.outcome`,
`summary`, the claim cleared, a `phase.verdict` row - and then STORES the status that record now
derives, on the shard and the index stub: `done` for a phase with no branch, nothing yet for one
awaiting its merge, whose `done` `close-phase.py`'s stamp stores. A hand edit of `status` made on
the phase branch before `close-phase` merged it used to be the only writer, so a phase worked on
its parent branch had nothing to hand `close-phase` and stayed in_progress for ever; the verb then
stored nothing, which left the same stale value for every reader that does not derive. It refuses
open work, a task-less phase, a second sign-off and a closed phase. `done` does the same for a bug
its task fixes: `fixed` and `fixedIn` go onto the bug in the index, the one write a close makes
there.

`reopen <taskId> --reason TEXT` is `/audit:run`'s re-open, which was a hand edit of the task's
close and its linked bug. It clears the close (`status` back to pending, `attempts` 0, `commit`,
`completedAt`, `outcome`, `verifiedBy`, `intentCheck`), puts a linked bug back to `in_progress`
with no `fixedIn`, and journals `task.reopen`. It refuses a task that is not done, and one whose
phase is signed off - done, or awaiting its merge - because that verdict is not re-decided, and a
stored `done` over an open task is a finding every later verb refuses on.

`done --no-change --reason TEXT` is the one close without a SHA, for a task whose answer was that
nothing needed to change, and it is refused when the task's declared files changed since its start
(`_no_change_moves`: a commit since the HEAD the task's `task.start` row records (`_start_head`),
touching one, or an uncommitted change to one; without that row, a commit since `startedAt` bounded
below by `baseRef` that no other task records as its own. Each entry is mapped to the git root as
`commit-task-work.stage_targets` maps it, and one outside the root is named as not asked): `commit` stays null and `outcome.noChange` records the reason and the HEAD
it was examined at (`_examined_head`; null, and said, when git cannot name one), which is the block
`_commit_trail.no_change_close` answers from for the doctor's no-SHA warning as well. `--intent
not-asked --intent-basis TEXT` records an intent question deliberately not put; `_done_flags_refusal`
refuses the word without its basis and every combination of the two closes' flags that names both or
neither, and `_status_facts.intent_unanswered` is what sign-off and `/audit:status` list: a done
task whose `intentCheck` is absent or reads `deferred` - still owed its phase review - and never
one carrying an answer, `not-asked` with its basis included.

`move <taskId> --to <phaseId>`, `block <taskId> --reason TEXT` and `note <taskId> --text TEXT` are
the hand edits operators kept making. `move` allocates with `_allocate_id` - what `next-id task`
prints - rewrites every reference through `_id_refs.rename`, writes `movedFrom`, and writes every
phase whose body changed plus the index through `_write_plan`, which snapshots all of them before
the first write so a refusal restores all of them. A second move nests the first as
`movedFrom.previous`; `_manifest_io.moved_from_ids` walks that chain for `_id_shape.next_task_id`,
which never mints one of those ids again, and for `_evidence_io.subject_aliases`, through which the
doctor and `reconcile` join runs recorded under an old id to the live task. `block` writes `status` and `blockedReason`
(cleared by the next `start`, whose row keeps it as the value it moved from); `note` appends one
`{at, text}` entry to `notes[]`, the one addition a started task takes. Each journals its own row -
`task.move`, `task.block`, `task.note`. `unblock <taskId> --reason TEXT` is the way past the
attempt ceiling `start` refuses at, `--force` included: on a task that has spent its attempts it
resets `attempts` to 0 and, on a blocked one, moves it to `pending` and drops `blockedReason`,
journaling `task.unblock` with the human's reason. A task with attempts left is refused
(`_unblock_refusal`) - `start` still runs it - so a count is never reset for a block about
something else.

`finding <phaseId>`, `resolve-finding <findingId>` and `correct <phaseId>` write a sign-off's
review record, which used to be hand-edited into the shard. `finding` appends entries in the
finding shape to `review.findings` - one from `--severity`/`--file`/`--issue`/`--resolution`,
or a review's whole array from `--findings-file PATH|-` in one write - refusing a missing field
or a severity outside `_phases.FINDING_SEVERITY` before the lock (a batch whole), and refusing a
phase that has already landed (`mergedAt` set); on a signed-off phase not yet landed it records
the finding and says which verdict it arrived after. `resolve-finding` sets a finding's
`fixTask`, `commit` and `resolution` from a DONE fix task's recorded commit; `reopen` of that
task removes the commit again (`_unresolve_findings`), and a `move` renames `fixTask` with the
task (`_id_refs.SCALAR_REFS`). `correct` rewrites `review.outcome` or `summary` text on a phase
that already has a verdict and never re-decides it. Every write of `review.outcome`, the two
`signoff` paths included, goes through `outcome_with_tally`, which derives the severity tally
from the list, so no one types it. Each journals its own row - `review.finding` (one per
finding), `review.resolve`, `review.correct`.

`settle [manifest]` stores every derived value a plan carries stale - a phase's `status`, a bug's
`status` and `fixedIn` (`_manifest_io.derived_disagreements`), and any index stub fallen behind its
shard (`_manifest_io.stale_stubs`) - under the index lock, revalidated, rolled back on findings,
with one `plan.settle` row naming each value it moved. It is the command `validate-manifest`'s
warnings name, and it only ever moves a value towards the derivation: a stored terminal status and
a person's `wontfix`/`not_a_bug` win inside the derivation, so settle cannot overwrite either.

`add-phase --park` writes the same phase `add-phase` builds as a parked proposal instead
(`PROP-<n>[-suffix]`; on a side branch the reserved phase id is the placeholder `P<n>-<suffix>`,
which `_proposals.plan_for` re-mints by the append rule and `apply_materialize` renames across
the whole plan through `_id_refs` - two branches parking one each both reserved the next plain
`P<n>` before, and the merged plan carried a clash the driver reported as a conflict), because phases are minted on the development
branch: a phase id is the one id that carries no branch suffix. A live `add-phase` on a side
branch is never refused; the first one on a branch prints a WARNING naming `--park`, read
back from the `phase.add` rows, which now record the branch (`_journal_io.DETAILS_KEYS`
carries `branch`). `_journal_cfg` is the one answer to which journal config a CLI row is
written and read with.

`next-id bug|prop|task --phase <id>` prints the id a hand-written record takes - a bug
(`commands/bug.md`), a parked proposal (`init.md`, `sync.md`), a bug's fix task or a moved task
(`bug.md`) are the records the model still writes by hand, and so the ids it used to compute by
hand as max+1; a moved task no longer is one - `move` takes the same allocator's answer in process. It reads the same allocator every scripted writer does, suffix and
reservations included, and writes nothing. Not `phase`: a phase is minted only by `add-phase`, which
writes it under the lock, where a task's phase is fixed before its id is asked for.

`couple --test <path> --sources <comma-separated paths> --basis-run <runId> --basis-head <sha>
[--phases <comma-separated ids>]` and `uncouple --test <path>` are the only writers of
`meta.coupling` - the record `derive-phase-gate.py`'s coupling arm reads to widen a derived gate
past what an importer listing alone would find. `couple` appends a new entry, or unions
`--sources` into an existing one for the same `test` and keeps that entry's first `learnedAt`
rather than overwriting it, because the couple is a fact learned once and re-confirmed, not
re-dated on every call. `uncouple` drops the one entry naming `--test` and refuses, exit 2, when
no entry names it - the same "an operation on something that is not there is an error, never a
silent no-op" rule every other verb here holds. `couple --test <path> --caught <runId>` is the
narrowest door onto the same key: it refreshes an EXISTING entry's `lastCaught`
to the `ts` of a full run whose runner named the test failing on a step no mute excused, and a
name the run gave that fits several coupled tests (`_evidence_io.resolve_named`) credits none of
them. It never creates an entry (a test with none is refused, exit 2), never changes `sources` or
`basis` (`--sources`/`--basis-run`/`--basis-head`/`--phases` beside it are refused), and never
moves `lastCaught` back: a catch at or before the recorded one, compared as moments through
`_evidence_io.stamp_moment`, writes nothing and exits 0 saying so. A row whose own
`selectionMiss` lists the test (`_evidence_io.own_miss`) is refused, exit 2, as `full-gate.py`
credits it no catch. Journaled as `coupling.caught`.

`bug-add "<title>" --severity low|med|high --description TEXT` (with optional `--files`,
`--repro`, `--expected` and `--actual`) is the only writer `/audit:bug add` uses for `bugs[]`: it
appends one bug in exactly the shape `commands/bug.md` spells - every key present, the unset
links `null` - with the id `next-id bug` would print, creating the list when the plan has none,
into the index alone, with a `bug.add` journal row. It exists because that shape used to be a
paragraph the model re-typed by hand on every report, and nothing checked that every key reached
the file.

`mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId>` and
`unmute --test <path>` are the only writers of `meta.muted`, the quarantine the gate runner
reads, for `couple`'s reason: one verb pair means one set of refusals on the way in. `mute`
refuses, exit 2, a missing `--bug` and an `--until` that is unreadable or already past, and
extends an existing entry only to a later day. It does not look the bug up itself: a `--bug` the
plan lacks is the validator's own finding on the revalidation, so the write is rolled back, exit
1, with the finding printed - one answer to "does this bug exist", not two. `unmute` removes
exactly the entry naming `--test`, and refuses, exit 2, when there is none. An expired mute is a
warning rather than a finding, so both run on a plan that carries one.

### `plugins/audit/scripts/usage/audit-usage.py`
`/audit:usage` — token spend, attributed, rendering its own final ASCII output (no box
drawing, no ANSI, no emoji) so the command file can print it verbatim without paying a model
to reformat a JSON rollup. With `--by phase|task|model|author|agent|day|hour|session|branch|
attr` it prints one focused table; without it, the full dashboard. `--backfill` re-reads every
transcript for the project from offset 0 and rebuilds the ledger — idempotent, and the only
path that rewrites rather than only appending. The lock it takes excludes only another backfill:
the metering hook appends with no lock, so each month's rewrite carries the rows appended to it
during the rebuild (`usage_ledger.rewrite_month`), a month with no file yet included. `--json`'s payload also
carries `planCost` (since P56.6): `_usage_economics.plan_cost_claim`, read against BOTH ledgers
this command's project has — the usage ledger already loaded for everything else, and
`_evidence_io.read_rows(project)` for the gate-scope and gate-reuse comparisons, which live in
the OTHER, evidence, ledger. Unfiltered by the CLI's own `--since`/`--phase`/etc: the three
comparisons it folds together are already narrow, so a window on top would only thin them
further. It finds the manifest through `_manifest_io.resolve_manifest` (its own `resolve_manifest`
wraps that call with the CLI's `--manifest` argument) rather than requiring one: the ledger still
renders with no plan at all, so a missing manifest is a note on stderr naming
`describe_unresolved`'s places-looked, never a refusal.

### `plugins/audit/scripts/manifest/_manifest_io.py` + `migrate-manifest.py` + `commands/layout.md` + `commands/migrate.md` (v0.15.0)
The **sharded manifest layout**. `_manifest_io.py` is the dependency-free dual-format loader/writer:
`load_manifest` reads BOTH the single-file form and the v3 index+shards form into the same assembled
dict (so every script + hook stays format-agnostic — it's wired into all five scripts' `main()` and
`hooks/_config.in_progress_task_map`); `split_manifest`/`save_sharded` write the sharded form (index of
`{id,title,status,shard}` stubs + `phases/<id>.json` bodies) atomically. The stub's `status` is a
MIRROR — the body is the source of truth and `_merge_phase` lets it win — kept because execution
order has to be computable without opening a shard, which is what the layout is for; it is refreshed
only when the value it copies moves, so a phase's own transition writes the index while the work
inside it writes only that phase's shard, and parallel phase branches still touch one stub each. A
run `claim` is not mirrored at all: it is per-run coordination with no reader that may not open the
shard.
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

The module also owns WHERE the manifest is: `resolve_manifest(project, explicit)` answers the
explicit argument when one was given, else `.claude/audit.config.json`'s `manifestPath`, else
`docs/audit/audit-plan.json`, and returns every place it looked so `describe_unresolved()` can
name them in a refusal. A config naming a path that does not exist is never followed by the
default — that would silently render some other plan than the one the project points at — so
`resolve_manifest` reports no path found there instead of falling through.

### `plugins/audit/scripts/manifest/_manifest_merge.py` + `merge-manifest.py` + `_merge_install.py`
**The manifest merged by record, so appends stop conflicting.** Every structural writer appends at
a list tail - a phase, a task, a bug, a `fileIndex` row - so two branches that each add a different
record write the same lines and git's line merge stops, in either layout: sharding moves a phase
RUN into its own shard, but every record that is ADDED still lands in the index. `_manifest_merge`
(L1, pure) merges three parsed documents: records matched by `id`, a `fileIndex` row as a set of
task ids, fields three-way. What stays a conflict is what a human must decide - one field changed
two ways, delete against change, and the same id added twice with different content, which is never
renumbered. The order is symmetric - base order, a side's additions after the record they followed,
tail runs at the tail, ties by a natural sort of the run's first id - because phase order is
execution order and merging in either direction must produce the same bytes. `render` does not
patch markers into one document: it renders each side WHOLE, every conflict resolved that side's
way, and the marker blocks are the line diff between the two. A block around one value cannot own
the comma on the sibling before it - a deleted last record, or two adjacent conflicts, left it
dangling - while two complete documents are valid JSON by construction, so keeping one side
throughout reproduces that side's document exactly. A value that is new on both sides merges as if
the base held an empty one of its shape (a `fileIndex` row two branches both create is a union);
a RECORD new on both sides is an id collision, and so is a shard `git` reports as added on both.

`merge-manifest.py` is the driver git calls with `%O %A %B %P`, and `install|uninstall|status`.
What git does with a driver was measured rather than read (git 2.50.1, recorded in the module
docstring): a driver that fails without writing leaves `%A` as ours with NO markers, and an exit
above 128 aborts the whole merge - so every failure path writes git's own line merge before exiting
1. A merged single-file plan is revalidated and only findings NEITHER side had fail it; an index or
shard cannot be validated alone and the driver says so. git config names a POSIX-sh shim under the
git common dir, never the plugin cache (which moves on every upgrade): the shim records the plugin
root, and when that root is gone - or the driver exits non-zero with `%A` unchanged, the
ImportError shape - it runs `git merge-file` itself. `resolve <plan> --renumber ours|theirs` answers the one collision the
branch suffix cannot prevent (two clones minting on the development branch): it reads the three
plans from the merge's COMMITS rather than from git's stages - in the sharded layout a phase minted
on both sides with one title merges its index cleanly and conflicts only in the shard file, so the
index has no stages to read - renumbers each id both sides minted on the side named through
`_id_refs`, merges again, and writes the plan through `split_manifest`, each file rendered against
the one conflict list. `.gitattributes` gets the manifest and its
shard glob; a clone that has not installed falls back to git's own line merge, which is why that
file is safe to commit. `_merge_install.replay_merges` is the doctor's measurement of what the
layout has cost: the recent merges whose two sides both changed the plan, replayed with
`git merge-tree --write-tree` and the driver swapped for `git merge-file`, which is what a
clone without it runs - a phase-count threshold would be a proxy for this number, and the
history can simply count it. It refuses `git log -- <plan>` on purpose: that history
simplification drops a merge resolved by taking one side. `_merge_install` (L1) names the install's pieces once and reads them
back, because `merge-manifest status` and the doctor's `merge driver` line must give one answer and
a layer-4 module may not reach an entry point. Cases: `tests/test__manifest_merge.py` (the merge) and
`tests/test__merge_install.py` (locating, and a quoted root read back), `tests/test_merge_manifest.py` (real git: the field report reproduced as a control, both
directions byte-identical, sharded, a stale shim, a driver that dies before writing).

### `plugins/audit/scripts/manifest/_id_shape.py`
**Ids two branches cannot both mint.** Every allocator is max+1 and max+1 is taken on one branch,
so two branches from one base both mint the next id and the record merge can only report the
collision - which side keeps the id depends on which was published first. Off the development
branch (`_branch.parent_branch`'s answer, plus every phase's own parent) an id carries a
three-character `[0-9a-z]` suffix drawn from the branch name: `BUG-12-k7m`, `P61-k7m`,
`P60.6-k7m`. The number ignores the suffix, so ids keep their order; a task in a phase already
carrying this branch's suffix does not repeat it. The alphabet is what a lock name, a shard file
name and a lower-cased branch component all take unchanged. `_manifest_vocab.ID_SUFFIX` is the
suffix's one spelling, read by `BUG_ID_RE` and by the allocators. What it cannot prevent - two
clones minting on the development branch itself - reaches the merge, which names it. Cases:
`tests/test__id_shape.py`.

### `plugins/audit/scripts/manifest/_id_refs.py`
**One id renamed everywhere the plan points at it.** `materialize` rewrote the references inside
its own payload and no other, and the merge driver's resolve verb needs every field - a rename that
misses one leaves a `blockedBy` that can never clear or a `fileIndex` row granting an edit to no
task. So the fields that hold another record's id are listed once (`SCALAR_REFS`, `LIST_REFS`, the
ids themselves, `fileIndex` values, every proposal payload), `phase_mapping` carries a phase's
tasks with it by prefix, and `collisions` refuses a rename onto an id the plan already holds before
anything is written. `movedFrom` is never rewritten: it is history, and rewriting it would make the
record say the move never happened. `renumber_duplicate_bugs` keeps its own logic on purpose - two
duplicates share one id, so no old->new mapping can tell them apart; only the bug's `taskId` can.
Cases: `tests/test__id_refs.py`.

### `plugins/audit/scripts/manifest/migrate-json-encoding.py`
**One JSON escaping, and the pass that gets the tree to it.** `_manifest_io.atomic_write_json`
used to take the escaping as an argument, so two writers produced two byte shapes for one
document: a title carrying an em dash came back re-spelled whenever the families alternated, and
a shard merge that should have shown the lines that moved showed the lines that were re-escaped —
on exactly the parallel phases the sharded layout exists to make possible. `json_document` is now
the single choosing site (literal UTF-8: the operator's editor and the merge tool already produce
it, and they are the two writers this plugin cannot change), `atomic_write_json` writes what it
returns and takes no encoding argument, and `_deps.json_encoding_violations()` fails the build on a
call site that passes one, on a choosing site that stops spelling its keyword, and on a writer that
serialises on its own. This command is how files written before that catch up: pointed at ONE
manifest it rewrites the index and every shard that index names — nothing else, and a `shard`
value pointing outside the index's own directory is refused by name rather than followed. The pass
is all-or-nothing: index lock → read and judge every owned file before touching any → refuse the
whole run on one that cannot be read or parsed → validate the assembled manifest **before** the
save → write only the files whose bytes change, atomically → re-read from disk and validate again,
rolling every file back byte for byte if it does not stand. It always reports all four classes,
including the empty ones, because "there was nothing to do" and "it never looked" are different
answers. `--dry-run` previews, `--json` emits the same four lists as the human report.

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
live nowhere else: a fragment module cannot render one. Its `<manifest>` positional is optional
too, resolved through `_manifest_io.resolve_manifest` the same way the other first-contact
commands are; `describe_unresolved` is what it prints to stderr, then exits 2, when neither the
argument nor the config nor the default names a file that exists. `--selftest` (includes XSS
cases).

### `plugins/audit/scripts/report/_report_page.py`
The report as a whole document, moved out of `render-report.py`: the report's vocabulary
(`_plural`, the gate's condition labels, which optional columns a plan has earned), the
phase-row builder, and `render_html` itself — the function that glues `_report_html`'s
fragments and `_report_usage`'s section into one self-contained page, or (with
`fragment=True`) into the same page with no document wrapper, for a Claude Code Artifact
whose host supplies its own. Layer 6, which its own edges decide. The verdict at the top of
the report is `/audit:status`'s own word, so `render_html` takes `verdict` as an INJECTED
callable and `render-report.py` supplies `_verdict`. That injection used to be forced by the
module map — the gate was reached through `_loader` as an entry point, so calling it from
here would have been a helper reaching up — and it has not been since the gate's conditions
came down to `_status_facts` at layer 2, which this module already imports for one
predicate. What keeps it is the stronger half: a renderer computing the verdict out of the
same facts would be a second opinion beside the command's, free to disagree with the word a
reader was given on the terminal. With no verdict supplied
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
ranked lists. The context line is where the rate basis lives: every cost in the section is
priced at read time by the resolved table (`priced_at_read`), so the phrase names that table and
its date. A project table declared with no date is said to be undated rather than given the
shipped table's date, and the rows that kept the figure stored when written, at a rate the
ledger never recorded, are counted in the same phrase. The trend's axis labels live **outside** the SVG:
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
on every `/api/*` call AND on the page itself (`X-Audit-Token`/`?t=`) — `do_GET`'s `/` route
makes the same Host and token checks inline, so reaching the Host check alone is not enough to
read the token the served HTML carries, but it answers a refusal differently: a person in a
browser tab reads plain text naming where the real URL lives, while `/api/*` stays JSON for the
script calling it. It tracks **one panel per project** via a
`.claude/audit-panel.json` pidfile (open/stop/status; stale pidfiles auto-cleaned), written
owner-only from the instant it exists, on POSIX, through a temp file in the same directory and an
`os.replace`, never through a plain write followed by a `chmod` — that order leaves a window,
on every launch, during which another local user could hold a readable descriptor on a live
credential. The pidfile carries a **build stamp** as well — written by `_write_pidfile` rather
than by `serve()`, so every pidfile this plugin writes has it and `--status` always holds both
halves of the comparison below.

**The pidfile is no longer the panel's only per-project artifact.** A detached launch
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

It also answers the question the first one hides: **would a clone of this repository load
the same thing?** `grade_entry` is a pure function stamping every row with `travels`
(`True`/`False`/`None`) and the `travelsBasis` behind it — `project` travels, `user` never
does, and a plugin travels only when the COMMITTED `.claude/settings.json` (read by
`_committed_settings`, never `settings.local.json` and never the home file) declares it in
both `extraKnownMarketplaces` and `enabledPlugins`, with the message naming whichever key is
absent. `_declares` matches a `plugin@marketplace` pair against whole path SEGMENTS, because
both the fetched (`cache/<marketplace>/<plugin>/<version>/`) and checked-out
(`marketplaces/<marketplace>/plugins/<plugin>/`) layouts are live and a real tree carries
backup directories a substring test would accept. Audit's own capabilities are exempt through
`_policy.required_names()` plus a path test — the plugin is what RUNS the plan. `discover`
takes a `scope`: `SCOPE_MACHINE` is the panel's question, `SCOPE_REPO` reads nothing under a
home directory at all, which is what lets the report and the CI gate state a verdict that is
the same on every machine. The scope is part of the cache key for that reason. `_mcp_entries`
replaced a function returning bare names, so an MCP row now carries the source it always
knew.

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
`_manifest_path`/`_read_json`/`read_config`, the `_load` wrapper, and the
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
`_panel_settings` from LAYER 2, the deepest inversion `KNOWN_LAYER_DEBT`
then carried, which is why `_panel_settings` moved up to layer 3 in the same change.

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

### `plugins/audit/templates/permissions-deny.example.json`
Byte-for-byte the JSON block `docs/research/guard-ownership-design.md` derives. An optional
`.claude/settings.json` fragment for users who also want Claude Code's own sandbox and
`permissions.deny` layer to refuse secret reads — it sits alongside this plugin's guards and
replaces no rule in them. `plugins/audit/tests/test_guard_secrets_read.py` parses `SECRET_PATH`'s
own compiled alternation rather than reading it by line, so a grouped extension or two
alternatives written on one source line are not merged or dropped; it pins that the template
parses and is byte-identical to the design doc's block, that every top-level alternative is
matched against an anchored shape for one of its known families (an unmatched alternative is
reported as drift unless named, with a reason, in the suite's own `_OMITTED_ALTS`), and that
EVERY member of every matched family — not only the first — carries its own `Read(...)` entry
in the template, individually.

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
is why a duplicated case id is the one defect that weakens every other proof in the tree. The rule reads the CALL
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

## 6. The command verbs, in full

The pipeline's command bodies carry the step driver's loop and each verb's own command line;
the rule a step needs is printed by `drive-phase.py` at that step, and each agent carries its
own in its prompt (`tools/measure-context.py --gate` holds the bodies under the pipeline-cost
design's ceilings, and `_refs.followed_anchor_drift()` holds that every followed rule names its
step or its prompt). What each verb writes, refuses and why moved out of the main loop's path
into `plugins/audit/reference/verbs-in-full.md`, a reference the plugin ships and no command
reads first - so `/audit:guide` and a reader of an installed copy still have it. The
explanation of what each script enforces stays beside that script's own section above
(`drive-phase.py`, `_refs.py`, `audit-task.py`), and is not repeated here.
