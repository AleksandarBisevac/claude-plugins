# quality-gates

A [Claude Code](https://code.claude.com) plugin marketplace with one theme:
**enforced** engineering discipline — plan gates, test gates, sign-off gates,
secret guards. Deterministic hooks, not prompt suggestions.

## Plugins

| Plugin | What it does |
|---|---|
| [**audit**](plugins/audit/README.md) | Manifest-driven, model-aware, test-driven audit/fix pipeline: `/audit` executes phases/tasks from a schema-validated JSON manifest (branch-per-phase, per-task model + skills, red-first TDD bug fixes, gated sign-off), `/audit:init` generates the manifest from a multi-agent codebase audit, and five guard hooks enforce plan-first development, secret safety and a TDD nudge. |

## Install

```
/plugin marketplace add AleksandarBisevac/claude-plugins
/plugin install audit@quality-gates
```

> **Before you install**, read [installing arms global hooks](plugins/audit/README.md#installing-arms-global-hooks)
> — the guard hooks activate in **all** your projects, by design.
> Requirements: Python 3.8+ reachable as `python3`, `python` or `py`
> (on Windows: run inside Git Bash).

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
