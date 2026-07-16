---
description: 'Audit pipeline: render a self-contained, interactive HTML + Markdown report (collapsible phases, filter/sort, optional AI summary, Save-as-PDF) — shareable as a CI artifact. Read-only (never mutates the manifest).'
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
manifest) and print the written paths.

**Optional AI summary (recommended).** Before rendering, compose a 2–4 sentence, plain-language
summary of the audit's current state — synthesize the phases' `desiredOutcome`/`summary`, notable
task `outcome`s, open bugs, and the rollup (`audit-status.py <manifestPath> --json`). Write it to a
scratch file (e.g. `<out-dir or manifest dir>/.audit-summary.txt`, via Bash) and add
`--summary-file <that file>` to the render command; the renderer shows it in a **Summary** box in the
HTML, the Markdown, and the printable PDF. It is passed to the renderer only — it does **NOT** modify
the manifest, so `/audit:report` stays read-only (no lock).

The HTML opens standalone (double-click): in-page text/status filtering, per-phase collapse, a
**Save as PDF** button (browser print → A4, all phases expanded) and a **Download .md** button — all
self-contained (inline CSS + JS, zero network fetches), publishable as a CI artifact. Never locks,
never mutates the manifest.
