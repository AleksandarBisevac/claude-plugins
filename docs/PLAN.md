# Plan — `audit@quality-gates`

**This is the canonical list of open work.** It is committed on purpose: the plan used to live
in `TODO.local.md`, which is in `.git/info/exclude`, so it could not travel to a new machine, a
new clone, or a new session that had not read this one's history. A plan nobody else can open is
a plan that has to be reconstructed from memory every time.

**How this file went wrong once already, on the day it was created.** It was built from what is
*in the repository* — the roadmap, `TODO.local.md`, the design docs — and it therefore missed an
entire plan of ~29 requirements that lived in `~/.claude/plans/`, written by a different session.
Nobody noticed until the user read this file and asked where those items were. The lesson is the
same one this file opens with, one level up: **a plan outside the repository does not exist.**
That plan is now at `docs/plans/2026-08-08-report-panel-ui-governance.md`. When a session plans
in `~/.claude/plans/`, copy it into `docs/plans/` before acting on it.

Every item below is written to be picked up **cold** — with no context beyond this file and the
repository. Each carries the same six fields, and the ones that cost the most to rediscover are
`Known` and `Do not` :

| Field | What it is for |
|---|---|
| **Goal** | What "done" means, in one sentence |
| **Why** | The reason it is worth doing — so a future reader can decide to drop it |
| **Files** | Where the work lands |
| **Verify** | The command whose exit code decides it, not a description of success |
| **Known** | What has already been measured or tried, so it is not measured again |
| **Do not** | The dead ends, with the reason each is dead |

Conventions every item inherits — these are not repeated per item:

- **Selftests are globbed, not enumerated.** Every `.py` under `hooks/` and `scripts/` must carry
  `--selftest` or CI breaks. Never reply with a hand-written list of suites.
- **Terminal output is pure ASCII.** No ANSI, no box drawing, no emoji.
- **The version lives in one place:** `plugins/audit/.claude-plugin/plugin.json`.
- **A release is one commit** that bumps the version and finalises the CHANGELOG section, plus an
  annotated tag — **pushed only after CI is green**, including the `windows-latest` leg. Tags are
  never moved.
- **Every claim in output carries the basis that makes it true.** Routing advice stays silent
  without evidence; the cost report prints its thresholds; a lock verdict prints why it believes
  the holder is alive.
- **Verify by exit code, never by grepping stdout.** Three false pass/fail reports came from
  grepping (`ALL PASS` — three suites end differently; `invalid` in ajv output; `$?` catching an
  `echo`). A red CI run is also not necessarily a test failure: during the July outage runs were
  `failure` with every job `cancelled` and zero executed steps. `gh run view <id> --json jobs`
  distinguishes them.
- **Fix the class, not the instance.** A reported defect is a category — audit every call site,
  state the rule, add the guard that would have caught it.
- **A plan outside the repository does not exist.** `~/.claude/plans/` and `TODO.local.md` are
  both invisible to the next machine, clone and session. Copy any plan into `docs/plans/` before
  acting on it, and record open work here. Both halves of that rule have already been broken
  once each.

Status as of 2026-08-08: **v0.27.0** tagged, four commits past it on `main`, 1225 selftest
cases across 22 suites, CI green on
`ubuntu-latest` and `windows-latest`. The entire T0–T3 roadmap in
`docs/strategy/2026-08-06-market-analysis.md` §9 is shipped except item 12, which is submitted
and awaiting review (**B1** below).

---

## Actionable now

### U1 — Report & Panel UI/UX overhaul + governance (the 2026-08-08 plan)

**Goal.** Finish the plan in `docs/plans/2026-08-08-report-panel-ui-governance.md`: 29
requirements (A1–A11 report, B1–B16 panel, C1–C2 extras) across 16 chunks and four
version-targeted governance releases.

**Why.** It is a direct response to the user's own UI/UX review of the plugin's two visual
surfaces — dead controls, lost filters, layout jumps, unclear forms, raw labels — plus four
capabilities the product does not have (monorepo areas, capability policy, tamper-evident
journal, in-product help). It is by a wide margin the largest body of open work in this repo.

**Where it stands** — verified against the tree, not read off commit titles. The status table is
in that file; in one line: **Report c1–c4 and Panel c1–c2 are done** (five commits,
`8529957`…`f05ae6f`), **Report c5–c8 and Panel c3–c8 are open**, and **all of workstream C
(v0.28 areas, v0.29 journal, v0.30 policy, v0.31 help) is untouched** — none of
`scripts/audit-journal.py`, `hooks/guard-capabilities.py`, `hooks/journal-writes.py` or
`agents/audit-guide.md` exists.

**Files.** `plugins/audit/scripts/render-report.py`, `panel-server.py`, `_ui_theme.py`; new
scripts, hooks and an agent for workstream C. Per-chunk file lists are in the plan.

**Verify.** Per the plan's own gates: `--selftest` on every touched script,
`node tools/capture-screenshots.mjs --check`, and now also
`node tools/check-report-interactive.mjs` on all three shipped reports.

**Known.**
- The plan's diagnosis of A2/A3/A4/A9 — *"stale install likely"* — **was wrong**. The confirmed
  cause is an IDE preview pane sandboxing inline `<script>`; see R1 below and the correction
  section in the plan file. Do not spend time on stale-install theories.
- c8's `file://` runtime click-through already shipped, separately, as
  `tools/check-report-interactive.mjs`.
- The plan's **Stage 2 green-light checkpoint** is binding and matches standing guidance: generate
  the report and panel screenshots, show them locally, and get explicit approval **before** any
  PR or push of visual work.
- Rollout order matters and is argued in the plan: **journal (v0.29) before policy (v0.30)**, so
  policy mutations are journaled from birth.

**Do not.**
- Do not re-plan this. The brief is written, the contracts are fixed (`_ui_theme.py`,
  `audit-journal.py`, the `policy` config block), and re-deriving them costs a day and produces
  something incompatible with the four chunks already shipped.
- Do not start workstream C before Report c5–c8 / Panel c3–c6: the plan's stages exist because
  the governance UI (panel c7/c8) consumes the Settings and confirm-flow work from c3 and c6.
- Do not take the requirement map as the spec — it is an index. The chunk sections carry the
  actual behaviour, including the c5 behaviour matrix the plan calls "the test spec".

### U2 — Multi-manifest workspace: decide it, do not drift on it

**Goal.** Answer one question: does the plugin need a workspace descriptor spanning several
manifests, or do `phase.area` + `meta.areas` cover the monorepo case well enough that it never
should?

**Why.** It is the one item of the 2026-07-29 roadmap
(`docs/plans/2026-07-29-per-phase-config-and-monorepo.md`) that never shipped, and it has sat
undecided since. Left alone it is the kind of thing that gets half-built twice.

**Known.** Everything else in that roadmap shipped: `phase.reviewSkill` (A), `phase.area` plus the
`areas` rollup and report column (B), and `/audit:worktree` (D) — verified against the tree.
Option C was written as a *design outline*, not a task, and the plan set its own decision
criterion: **decide after dogfooding A/B on a synthetic monorepo.** That dogfooding has not
happened. The 2026-08-08 plan's `meta.areas` registry (v0.28) is a richer successor to B and
pushes further down the single-manifest road — evidence toward "C is not needed", but not the
decision.

**Verify.** A written decision in this file: either C moves to *Decided against* with the
reasoning, or it becomes a real item with a scope. Not code either way, until it is decided.

**Do not.** Do not start building a workspace descriptor because it appears in an old plan. The
submodule preflight already forbids one audit spanning repos, which is the constraint C exists to
work around — and `meta.areas` may make that unnecessary.

### R1 — The report's interactivity, reported broken — CAUSE FOUND 2026-08-08

**Cause: an IDE preview pane, which sandboxes inline `<script>`.** The page renders
completely and looks finished while every interaction silently does nothing. Not a repo defect —
but the report said nothing about it, which made it indistinguishable from a broken product.

**Fixed** by making the report say so itself: a banner rendered into the HTML, removed by the
script's very first statement. Visible exactly when it is true. The report already had a
`<noscript>` for this — the right intent with a mechanism that cannot fire, since `<noscript>`
renders only when scripting is *disabled*, and a preview pane leaves it enabled and strips the
inline script. That note stays for the disabled case; it just could not be the only signal.

`tools/check-report-interactive.mjs` asserts the banner is **gone** after load, so its absence is
live proof the script ran and the banner can never rot into a lie.

**Why.** The rendered report is the product's best surface. A user opening it and finding that
filtering, search, phase expand/collapse and clicking all do nothing is a total failure of that
surface, whatever the cause.

**Files.** `plugins/audit/scripts/render-report.py` (the `_SCRIPT` block, roughly lines 640–1110).

**Verify.**
```bash
node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html   # see R2
```

**Known — do not re-run these, they all pass.** Reproduction was attempted on 2026-08-08 against
the exact committed file and came back clean every way it was tried:

| Attempt | Result |
|---|---|
| `http://` in Chromium — expand-all, collapse, phase click, filter miss/hit, clear | all correct |
| `file://` in Chromium — same set | all correct, **zero page errors** |
| `file://` in WebKit (Safari's engine) — same set | all correct, zero page errors |
| Real mouse + keyboard (`page.click`, `page.keyboard.type`) rather than synthetic events | all correct |
| Hit-testing `document.elementFromPoint` on the filter input, expand-all, a phase cell and a status chip at 1280/1512/1920/2560/820 px | every control reachable; nothing overlays them |
| Committed example vs. a fresh render | byte-identical except the embedded generation timestamp |

**Do not.**
- Do not assume the script is dead because a synchronous check after dispatching `input` shows no
  change — **the filter is debounced by 90 ms**. Wait 250 ms before asserting. This produced one
  false "the whole script is broken" reading already.
- Do not chase `localStorage` throwing on `file://`: all four uses are already inside `try/catch`
  (`render-report.py` lines 666, 672, 763, 764).
- Do not chase a CSP meta tag: the document has none, only `charset` and `viewport`.
- Do not chase `var grouped = document.querySelector('table.phases')` being null: the table is
  emitted with exactly that class, and it resolves.

Also checked, after R2 existed: **all three shipped reports** — the acme example,
`docs/index.html` (the live demo) and `docs/demo-large.html` (40 phases) — pass all 12
interaction checks. So this is not one stale artifact.

**Left to try.** Firefox (its Playwright build is not installed here —
`npx playwright install firefox`); whether the file is being opened through something that strips
scripts (an IDE preview pane, a Markdown viewer, GitHub's blob view rather than a browser); a
browser extension blocking inline script; a hard-refresh, in case a cached older copy is being
served. **Ask before building anything** — the cheapest next step is one question about how the
file is opened, not more code.

**Note for whoever picks this up.** Five commits landed after the v0.27.0 tag from a different
session (`8529957`…`f05ae6f`, report and panel UI). If this turns out to be real, they are the
place to look first — and R2 now guards that whole surface.

### R2 — CI asserts the report renders, never that it works — DONE 2026-08-08

**Goal.** A CI step that drives the rendered report in a headless browser and fails the build if
filtering, expand/collapse or the status chips stop working.

**Why.** This is the durable fix for R1's whole class, and it is worth doing whether or not R1
turns out to be a repo defect. Today `.github/workflows/ci.yml` only greps the output for
strings (`grep -q 'id="usage"'`). A JavaScript error that kills every event handler leaves all
those strings intact, so the report can ship completely inert with CI green — and the interactive
layer is a third of `render-report.py`.

**Files.** New `tools/check-report-interactive.mjs`; a step in `.github/workflows/ci.yml` beside
the existing "Demo GIF still shows what it claims" step, which is the same pattern (assert the
behaviour, not the bytes).

**Verify.** Proven to fail, not just to pass:

| Input | Exit |
|---|---|
| the three shipped reports | 0 |
| a `TypeError` injected into the script (handlers never wire) | 1, naming 9 dead interactions |
| the filter stubbed to match everything (handlers fine, filter inert) | 1, naming 2 |
| a missing file / no argument | 2 — never 0, so a missing dependency is not read as a pass |

`grep -q 'id="usage"'` — what CI checked before — **passes on both broken variants**.

**Known.** `playwright` is already available (`/Users/aleksandarbisevac/node_modules/playwright`,
1.56.0) and the repo already drives it from `tools/capture-screenshots.mjs`, so the pattern and
the dependency both exist. Chromium alone is enough; do not install three engines in CI for this.
The working probe from R1 is in this session's scratch and is about 30 lines: render the example,
open `file://`, click the phase title, type in `#audit-q`, assert the visible phase and task
counts change.

**Do not.** Do not assert on screenshots — that is `capture-screenshots.mjs`'s job and it makes
this check fail on unrelated styling. Assert on counts of visible rows and the `audit-count` text.

---

## Blocked on something outside this machine

### B1 — Community marketplace listing (roadmap item 12)

**Goal.** `audit` appears in the `claude-plugins-community` catalog.

**Status.** Submitted 2026-08-07 through the Console form
(<https://platform.claude.com/plugins/submit>) as `audit`, path `plugins/audit`. Awaiting
automated security screening, then human review — the docs say "a few days". Nothing to do but
check.

**Verify.** Search the catalog for the name rather than trusting a notification:
```bash
curl -sf https://raw.githubusercontent.com/anthropics/claude-plugins-community/main/.claude-plugin/marketplace.json \
  | python3 -c 'import json,sys; ns=[p["name"] for p in json.load(sys.stdin)["plugins"]]; print("audit" in ns, len(ns), "plugins")'
```

**Known.** Catalog size is the signal that the pipeline is moving: **2287** at submission
(2026-08-07), **2291** on 2026-08-08 — four landed, ours not among them, so the queue is being
worked. Once listed, the entry pins a commit SHA and CI bumps the pin as commits land, so nothing
needs re-submitting; the catalog file itself carries the `sha`, which is how that was verified
rather than believed.

**Do not.** Do not confuse this with the **official** directory — that one is curated at
Anthropic's discretion, has no application process, and this form does not add anything to it.
Do not re-submit while waiting.

### B2 — Live Azure DevOps round-trip

**Goal.** `/audit:sync` proven against a real Azure DevOps organisation, not only its selftests.

**Why.** ADO sync is a headline feature with zero real-world evidence behind it. Everything known
about it comes from tests written against the same assumptions as the code.

**Files.** `plugins/audit/commands/sync.md`, and whatever the run exposes.

**Verify.** Create a work item, run `/audit:sync`, confirm the id lands in the manifest, change
the status on both sides, and confirm the conflict path behaves as documented.

**Blocked on.** An ADO org and a work item. Cannot be closed from this machine.

### B3 — Headless gate in a real team repository

**Goal.** Prove `docs/examples/azure-pipelines.yml` fails a build for the right reason.

**Why.** The CI-gate story is currently only exercised against this repo's own manifest.

**Verify.** Copy the pipeline into a team repo, open a PR that violates a gate condition
(`open-high-bugs` is the easiest), and confirm the build fails naming that condition — then that
it passes once the condition clears.

**Blocked on.** A team repo. Cannot be closed from this machine.

---

## Decided against, with the reason

These are **not** backlog. They were considered and closed; each is listed so the decision is not
silently re-litigated in a new context.

### D1 — Requiring a lock, rather than honouring one

Since v0.27.0 the plan gate denies a manifest or shard write while **another live session** holds
the governing lock. It does **not** require that you hold a lock to write at all. A session that
simply never acquires one writes freely.

**Why it stays that way.** Denying an unlocked manifest write would break `/audit:init`, every
hand edit, and every read-only-turned-write path. The lock is honoured, not required. Revisit
only if someone hits the gap in practice — and note the hazard C1 closed was two *live* writers,
which this already covers.

### D2 — Splitting the marketplace (roadmap item 14)

`audit-guards` (hooks only) and `audit` (the orchestrator), for two adoption ramps.

**Why deferred.** Observe-by-default removed most of the rationale: the guards no longer deny in
a repo with no manifest, so taking the whole plugin costs a colleague nothing. Revisit if someone
actually asks for the hooks alone.

### D3 — Extending the lock across clones and machines

`--git-common-dir` is shared by worktrees of one clone and by nothing else — verified by comparing
absolute paths (clones do **not** share it; worktrees **do**).

**Why it stays that way.** The consequence is no longer silent: an unlocked concurrent run
produces a merge conflict you must resolve, not a corruption you never notice. `phase.claim`
covers the cross-machine same-phase case by the same mechanism. See
`docs/design/audit-concurrency-report.md`.

### D4 — ID namespacing (option O2 in the concurrency report)

**Retracted.** Its entire justification was that ID collisions merge silently. Measured on
2026-08-07 against the sharded layout with real clones: they **conflict**. Sharding moved every
id-allocating write into the index, so two allocations of the same kind share a hunk. O2 would
make `BUG-4` permanently worse to read and type in exchange for a collision git already reports.

### D5 — Optimising the lock check's 11 ms

`manifest_lock_conflict` costs ~19 ms on a manifest write, 11 ms of which is
`git rev-parse --git-common-dir`. Ordinary source edits are unaffected (0.14 ms — the check does
not fire, because nothing but a manifest path has a governing lock).

**Why it stays that way.** Resolving the git dir by hand would be a second implementation of
something git already answers, and two implementations that can disagree is the exact problem
v0.26.0 was spent removing. The hook budget is 10 seconds.

---

## Recurring, not tasks

These come back every time; they are not boxes to tick.

- **After a release**, refresh the locally installed copy:
  `claude plugin marketplace update quality-gates` → `claude plugin update audit@quality-gates` →
  `/reload-plugins`. Note the marketplace is registered here as a `directory` source pointing at
  this checkout, so "update" re-reads the working tree, not GitHub.
- **When `/audit:*` misbehaves**, check for a stale project-scope install shadowing the user-scope
  one: `claude plugin list | grep -c audit@quality-gates`. Two project pins remain at 0.14.0 in
  `~/Desktop/databridge/test-mono-expo` and `~/Desktop/databridge/db_embed/db-embed-platform`.
  Removing them would move those repos from always-on deny (pre-0.20 behaviour) to the
  evidence-graded gate — a behaviour change in someone's work repo, so ask first.
- **Keep `docs/strategy/2026-08-06-market-analysis.md` §1.2 and §6 frozen** at their 2026-08-06
  measurements. Live figures belong in that document's status table, never inside the frozen
  sections. Half-freezing them — updating the test count in place while `Releases: 24` stayed
  beside it — has already happened once across three commits.

---

## Shipped (context, not work)

The full roadmap is in `docs/strategy/2026-08-06-market-analysis.md` §9 and every release is in
`CHANGELOG.md`. Summarised here only so a cold reader knows what is already true:

- **T0** (v0.17–v0.19): tags pushed, live demo regenerated and gated in CI, screenshots automated
  with assertions, repo topics and badges.
- **T1** (v0.20.0): evidence-graded plan gate + `enforce: true`, `/audit:doctor`, free-first
  quickstart (`/audit:usage --backfill`), the eight §8 defects.
- **T2** (v0.21–v0.23): deterministic `/audit:status` render, budget as a gate, report as an
  Artifact, thin skills + ADR amendment, the enforcement essay, the rate-basis sweep.
- **T3** (v0.24–v0.25): report visual identity — verdict-led hero, the gate rail drawing
  `blockedBy`, app shell on report and panel, data-driven column density; the demo GIF, asserted
  by CI rather than trusted; report scalability (the filter's per-keystroke DOM re-query).
- **v0.26.0**: three rules that were right only for this repo — the test-file exemption knew only
  the JavaScript spelling; the plan gate denied the orchestrator its own phase shards on a custom
  `manifestPath`; the concurrency lock judged its holder by a clock instead of asking whether the
  process is alive.
- **Two-session E2E, 2026-08-08.** The v0.27.0 enforcement driven end to end in a sandbox
  (`~/.claude/jobs/*/tmp/e2e2/shop`) with two live processes, two session ids, a sharded manifest
  at a non-default path, and the hook payload id deliberately different from the env id — the
  real shape, not the selftests' shape. Every step behaved: A takes `phase-P1` and writes its own
  shard (allowed); B is refused the same lock with A's identity and basis (exit 3); B ignores that
  and edits the shard anyway (**denied**, naming A); B takes `phase-P2` instead and both write
  their own shards in parallel; A is killed, so the lock reads abandoned at once rather than after
  an hour (exit 4); B writes P1's shard pre-takeover (allowed, and the Post pass says the lock is
  still A's); B takes it over properly (Post goes silent); both release cleanly. One boundary
  confirmed by the run and worth knowing: B *was* allowed to edit A's **source** file, because
  `src/pricing.py` is in an `in_progress` task and the lock guards the manifest, not the tree.
- **v0.27.0**: the lock stops being advice — the plan gate refuses a manifest write held by
  another live session. Includes the discovery that a session has **more than one name**
  (`$CLAUDE_CODE_SESSION_ID` in Bash vs. the hook payload's `session_id` — different values), which
  also silently broke phase attribution in the token ledger.
