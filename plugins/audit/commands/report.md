---
description: 'Audit pipeline: render a self-contained HTML + Markdown status report (phase progress, task tables, bug rollup) — shareable as a CI artifact. Read-only.'
argument-hint: '[--out-dir <dir>]'
allowed-tools: Read, Bash
---

# /audit:report — render the status report

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run preflight steps 1–2 only
(read-only: no git-root/submodule check, no lock).

Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render-report.py" <manifestPath>`
(pass `--out-dir <dir>` through from `$ARGUMENTS` when given; artifacts otherwise land next to the
manifest) and print the written paths. The report is self-contained HTML + Markdown (inline CSS,
zero network fetches) — publishable as a CI artifact. Never locks, never mutates.
