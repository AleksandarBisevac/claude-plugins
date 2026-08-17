---
description: 'Audit pipeline: render a self-contained, interactive HTML + Markdown report (collapsible phases, filter/sort, optional AI summary, Save-as-PDF) — shareable as a CI artifact, or published to a link with --share. Read-only (never mutates the manifest).'
argument-hint: '[--out-dir <dir>] [--share]'
allowed-tools: Read, Bash, Artifact
---

# /audit:report — render the status report

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run preflight steps 1–2 only
(read-only: no git-root/submodule check, no lock).

Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report/render-report.py" <manifestPath>`
(pass `--out-dir <dir>` through from `$ARGUMENTS` when given; artifacts otherwise land next to the
manifest) and print the written paths.

**Optional AI summary (recommended).** Before rendering, compose a 2–4 sentence, plain-language
summary of the audit's current state — synthesize the phases' `desiredOutcome`/`summary`, notable
task `outcome`s, open bugs, and the rollup (`audit-status.py <manifestPath> --json`). Write it to a
scratch file (e.g. `<out-dir or manifest dir>/.audit-summary.txt`, via Bash) and add
`--summary-file <that file>` to the render command; the renderer shows it in a **Summary** box in the
HTML, the Markdown, and the printable PDF. It is passed to the renderer only — it does **NOT** modify
the manifest, so `/audit:report` stays read-only (no lock).

The HTML opens standalone (double-click): in-page text/status filtering, area chips when the plan
tags areas (they gate phases, like the status chips, and travel in the shareable `#!` hash as
`a=`), per-phase collapse, a **Save as PDF** button (browser print, all phases expanded, either
orientation) and a **Download .md** button — all
self-contained (inline CSS + JS, zero network fetches), publishable as a CI artifact. The Usage
section adds author chips when the ledger records more than one author — they scope that section's
per-author views only, because tasks record no author to filter by, and the page says so — and a
Month-by-month table once the ledger spans two calendar months, whose plan columns count the whole
project by event month. Never locks, never mutates the manifest.

## `--share` — publish the report to a link

A report on disk is shareable only by sending the file. `--share` renders the same report as a
hosted page instead, so a reviewer who has never installed this plugin can open a URL.

**Ask before publishing, every time, and say what is in it.** Publishing sends the report to
claude.ai. The page starts private, but it leaves this machine, and what it carries is the plan
itself: phase and task titles, `desiredOutcome` prose, the file paths under audit, commit hashes,
open bug descriptions and — when `usage.showCost` is on — what the work cost. Some of that is
ordinary; some of it names internal systems. Name those categories in the question rather than
asking a bare "publish?", and do not publish on a `--share` in the arguments alone. This is the one
outward-facing thing any `/audit:*` command does, and the rest of this plugin's guards exist
precisely so that nothing leaves without a decision behind it.

Then:

1. Render the embeddable form — **not** the standalone file:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report/render-report.py" <manifestPath> --format artifact`
   (add `--out-dir`/`--summary-file` exactly as above). It writes `<basename>.artifact.html`
   beside the normal outputs and never overwrites them.
2. Publish that path with the **Artifact** tool. Give it `favicon: "🛡"`, and a `description` that
   states the rollup in one line — for example *"Audit of acme-store: 3 of 5 phases signed off, 2
   open bugs."* Take the title from the report's own `<title>`; do not invent a different one.
3. Print the returned URL next to the local paths, and say plainly that the link is private until
   shared.

**Re-publishing.** Updating an audit means re-rendering the same report, so pass the same file path
to update the same URL rather than minting a second link for the same project — a stale audit link
that still resolves is worse than no link. For a report published in an earlier session, pass that
artifact's `url`; find it with the Artifact tool's `list` action when you do not have it.

Why the separate format: an Artifact supplies its own `<!doctype>`, `<head>` and `<body>`, so
publishing the standalone file would nest a second document inside the first. The fragment carries
the same report — same tables, same usage section, same embedded Markdown twin — without the
wrapper, and without the report's own theme toggle, since the host owns the theme there and stamps
the same `data-theme` attribute the toggle would fight over.
