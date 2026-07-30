# quality-gates

A [Claude Code](https://code.claude.com) plugin marketplace with one theme:
**enforced** engineering discipline — plan gates, test gates, sign-off gates,
secret guards. Deterministic hooks, not prompt suggestions.

### ▶ See it

A live, interactive audit report (search, filter, collapsible phases, Save-as-PDF) — nothing to install:

**[aleksandarbisevac.github.io/claude-plugins](https://aleksandarbisevac.github.io/claude-plugins/)** · or read the [worked example](examples/).

[![An audit report: summary, progress, phases and bug list](docs/screenshots/overview.png)](https://aleksandarbisevac.github.io/claude-plugins/)

## Plugins

| Plugin | What it does |
|---|---|
| [**audit**](plugins/audit/README.md) | Manifest-driven, model-aware, test-driven audit/fix pipeline: `/audit:status`, `/audit:run`, `/audit:phase` (and siblings) execute phases/tasks from a schema-validated JSON manifest (branch-per-phase, per-task model + skills, red-first TDD bug fixes, gated sign-off), `/audit:init` generates the manifest from a multi-agent codebase audit, `/audit:migrate` shards it into one file per phase for **parallel phases across git worktrees** (fewer tokens per run, conflict-free merges), a `/audit:panel` control panel manages config + composition in the browser, and guard hooks enforce plan-first development, secret safety and a TDD nudge. |

## Install

```
/plugin marketplace add AleksandarBisevac/claude-plugins
/plugin install audit@quality-gates
```

> **Before you install**, read [installing arms global hooks](plugins/audit/README.md#installing-arms-global-hooks)
> — the guard hooks activate in **all** your projects, by design.
> Requirements: Python 3.8+ reachable as `python3`, `python` or `py` (CI verifies on 3.12)
> (on Windows: run inside Git Bash).

## Quickstart

In any git repo you want to audit:

```
/audit:init            # interview → generates a schema-valid audit manifest
/audit:status          # see phases, tasks, bugs, and what's ready now
/audit:migrate         # (optional) shard the manifest → parallel-safe phases across worktrees
/audit:panel           # open the browser control panel to tune config + composition (open/stop/status)
/audit:phase P0        # run the first phase: branch → tasks (red-first TDD) → gated sign-off
/audit:report          # render the shareable HTML + Markdown report
```

`/audit:init` interviews you (scope, dimensions, size) and writes the manifest;
everything else reads and updates it. The report is one self-contained file
(open it in a browser, or **Save as PDF**). See the [worked example](examples/)
for what a manifest and its report look like, or the [plugin README](plugins/audit/README.md)
for the full command reference.

## This repo, dogfooded

`docs/audit/audit-plan.json` is this repository's own roadmap written as an
`audit` manifest — CI validates it with the plugin's own validator on every
push. Open it for a real-world example of phases, tasks, reciprocal bug links
and a fileIndex.

## Docs

- [Plugin README](plugins/audit/README.md) — install, quick start, configuration, extending
- [CHANGELOG](CHANGELOG.md) · [SECURITY](SECURITY.md) — threat model & what the guards do NOT guarantee · [CONTRIBUTING](CONTRIBUTING.md)
- [PLUGIN-BUILD-GUIDE](PLUGIN-BUILD-GUIDE.md) — how this plugin is put together, file by file

License: [MIT](LICENSE)
