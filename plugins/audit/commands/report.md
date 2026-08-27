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

## What the report says about test runs

**Earned by a pointer and by nothing else.** A subject carries `testEvidence` once a run has
been recorded against it, and a pointer — on a task or on a phase — is what turns this whole
surface on: the two filter rows, the phase marks, the drawer's third group and the Markdown
twin's column. The `tests` column itself is earned one step narrower, by a *task* carrying
one. A gate the plan merely declares earns nothing, deliberately: reading declarations
instead would put a column of `No evidence` on every manifest written before the field
existed, so a plan pointing at no recorded run renders exactly as it did before any of this
shipped, and upgrading the plugin changes not a byte of a report somebody already published.

**The word comes from the ledger, not from the plan.** `testEvidence` is a cache holding a
`runId`, a `status` and a time; the record is the append-only file beside the manifest
(`evidence.dir` in `.claude/audit.config.json`, else `<manifest dir>/evidence`). The badge
renders what the row that `runId` names says, so a cache that has drifted from the record
never decides what the report prints. A ledger this checkout cannot read therefore leaves
every pointer reading `Pointer without evidence` rather than reading clean: *the plan names
a run* and *the run is here* are two claims, and only the second one failed.

**A separate sentence for each way there is no run, never one grey blob** — they send a
reader to different places:

- **`No gate configured`** — neither the task's `tests.gate` nor its phase's `testGate`
  declares anything, so nothing could have run. A fact about the plan, not about the work.
  It is answered *before* the evidence boundary below is consulted: a gate that was never
  declared could not have run either side of the moment recording began, so calling that
  work *excused* would imply running something would have helped.
- **`No evidence`** — a gate is configured and no run has been recorded against it. Absent
  means *no run was recorded*, never *failed*: a manifest written before the field existed,
  a task nobody has run and a block somebody deleted are one state.
- **`Before recording`** — the work finished before the moment this plan could first have
  recorded anything (`meta.evidenceSince`, or the earliest run in the ledger, whichever is
  earlier). This is the state a plan adopted **mid-flight** is full of, and it is the one the
  `no-test-evidence` gate condition **excuses** rather than fails — so without a word of its
  own the surface would have shown a wall of `No evidence` while the gate reported green, and
  no reader could tell *excused* from *neglected*. The badge carries the boundary's own basis,
  so the excuse is checkable where it is claimed.
- **`Completion undated`** — the plan calls the work done, records no run, and says nothing
  about *when* it finished, so it cannot be placed against that moment at all. The gate
  **fails** this one and names it apart from the case above, because the repair differs: set
  the completion stamp, rather than run the gate.
- **`Pointer without evidence`** — the plan names a run this checkout's ledger does not
  carry. That is the one saying the record itself is missing, and `/audit:doctor` is what
  says which direction it broke in.

The class each subject falls in comes from the same function the gate buckets its verdict
with, so the badge and the exit code cannot disagree. Each is a value of `data-tev`, so the
`Test gate` filter row separates them.

**The badge is the verdict and nothing else; the observations sit beside it** as separate
marks — `tree mutated`, `tree unknown`, `no overlap`, `coverage unknown`, `checks unknown`.
A gate can fail *and* rewrite the tree, and a reader who fixed the failure would otherwise
meet the rewrite afterwards, in a commit. `tree unknown` and `coverage unknown` are not
quieter versions of the clean answer either: no comparison was made, so a rewrite cannot be
ruled out.

**Two filter rows, because they are two axes.** `Test gate:` selects on what a run
answered, `Observed:` on what else it noticed; one selection each, pressing the same chip
again clears it, and both travel in the shareable `#!` hash as `tev=` and `tevf=` beside the
area chips' `a=`. Independent on purpose — *which gates rewrote the tree* is a question the
verdict column cannot answer, whatever it says.

**A phase row carries two marks, labelled apart**: `sign-off`, the run the gate this phase
signs off with last recorded, and `tasks`, its tasks counted by what each one's own last run
said. Different work, different files — one mark for both would claim a measurement nobody
made.

**The drawer grows a third group, `test evidence`**: the run id and when it was recorded,
the scope and the attempt, how long it took, how much ran, what the tree comparison and the
coverage question each answered **carrying the basis that produced the answer**, one line
per step (its exit code, its check count, and its command where the manifest publishes that
command — a program name and a digest where it does not), and the runs before this one
folded away under `Earlier runs`. It is drawn for every task once the column is earned, so a
task with no run of its own says which of the three silences it is in rather than being
blank.

**The bugs table gains a `test gate` column, and it is borrowed.** A bug carries no gate of
its own; what proves one fixed is the run over the task that fixed it, so the cell shows
that task's badge and says `via <taskId>`. Drop the second half and a reader believes the
*bug* was measured, which nothing in this plugin ever does. A bug with no fix task yet, and
a bug naming a task this plan does not carry, each say so instead of sharing a cell with a
verdict.

**The Markdown twin carries the verdict and nothing more** — a `tests` column holding the
raw key (`passed`, `no-evidence`, `no-gate`), no observation marks, and no column in its
bugs table. That is the diffable form: a run that changed a verdict shows up in a diff of two
renders, and everything else the run noticed stays in the HTML, where there is room to print
its basis beside it.

## `--share` — publish the report to a link

A report on disk is shareable only by sending the file. `--share` renders the same report as a
hosted page instead, so a reviewer who has never installed this plugin can open a URL.

**Ask before publishing, every time, and say what is in it.** Publishing sends the report to
claude.ai. The page starts private, but it leaves this machine, and what it carries is the plan
itself: phase and task titles, `desiredOutcome` prose, the file paths under audit, commit hashes,
open bug descriptions and — when `usage.showCost` is on — what the work cost. Once a run has been
recorded it also carries what the gate did: the gate commands as the manifest publishes them, each
step's exit code and duration, and the repository paths a run rewrote or was found to cover. Some
of that is ordinary; some of it names internal systems. Name those categories in the question rather than
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
