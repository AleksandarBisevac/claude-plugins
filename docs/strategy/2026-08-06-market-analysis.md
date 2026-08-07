# Market position and roadmap — `audit@quality-gates`

**Status:** analysis. No decision is made here except one recommendation, in §5, which is
flagged as such. Everything else exists so a decision can be made with eyes open.

**Date:** 2026-08-06 · **Analysed version:** v0.19.0 (local), v0.16.0 (published)

**Goal this is written against:** engineering credibility as a portfolio artifact, plus
internal rollout across a team's projects, with the plugin remaining openly available.
Install count is not the success metric. That ranking is what puts first-run experience
above distribution tactics in §6 — under a mass-adoption goal, T2 would come before T1.

### Implementation status

The analysis below is kept as written, at the state it described, because a roadmap that
quietly edits its own premises cannot be checked against what actually happened. What has
since shipped:

| | |
|---|---|
| **T0 — complete** (PR #15) | v0.17.0–v0.19.0 pushed with tags · live demo refreshed and gated · scale demo regenerated from a valid manifest · screenshots automated with assertions · topics, homepage and badges set |
| Found during T0, not predicted here | The report's progress bars had **never** painted (§8) · a missing semicolon had killed every animation in the stylesheet · the scale demo had been serving an "INVALID MANIFEST" banner |
| Corrected here | The empty-bar root cause (§8), and the test-case count (675 → 721 across 18 suites; the 686 figure was a static grep, not a runtime count) |
| Shipped since | **T1 complete** in 0.20.0 (evidence-graded plan gate · `/audit:doctor` · free-first quickstart · the eight §8 defects) · **T2.9 + T2.10** in 0.21.0 (deterministic `/audit:status` render · budget as a gate) · **T2.11 + T3.16 + T3.13** in 0.22.0 (report published to a link · thin skills, ADR amended · the enforcement essay) · **the rate-basis sweep** in 0.23.0 (five cost surfaces name their price table; `/audit:usage` honours a configured `manifestPath`, so `showCost: false` works on non-default layouts) · **T3.15 complete** in 0.24.0 (verdict-led hero · the gate rail drawing `blockedBy` · app shell on report and panel · data-driven column density · all twelve screenshots recaptured) |
| Corrected by events | The §6 threat "the ADR watches for the wrong signal" was the accurate half of that entry; the fix was neither NO-GO nor migration but shipping both layouts — see the v0.22.0 amendment in `CONTRIBUTING.md` |
| **Premise of T2.12 was wrong** | §6 and the T2 table both say external plugins are *submitted to the official directory with automated screening*. They are not. `claude-plugins-official` is **curated by Anthropic at its discretion — there is no application process, and the submission form does not add plugins to it**. The form feeds `claude-plugins-community` (installed as `@claude-community`), which is where third-party submissions land after review. The achievable item is the **community** marketplace, and the auto-propagation claim survives intact in a sharper form: approved plugins are pinned to a commit SHA and CI bumps the pin as commits land, with the public catalog syncing nightly. Submission is in-app — [claude.ai](https://claude.ai/admin-settings/directory/submissions/plugins/new) (needs a Team/Enterprise org with directory access) or [Console](https://platform.claude.com/plugins/submit) (individual authors). `claude plugin validate ./plugins/audit --strict` is the same check the review pipeline runs; it exits 0 here. |
| Still open | T2.12 (**community** marketplace submission — see above). #14 deferred pending re-assessment — observe-by-default largely removes its rationale |

---

## 1. Where this stands

### 1.1 The blocker

```
origin/main   9453a36   v0.16.0   2026-07-30 10:21 +0200
main          521fbaf   v0.19.0   [ahead 3]

  521fbaf  release: v0.19.0 — spend becomes a signal
  e20c302  release: v0.18.0 — the usage dashboard
  e5c2179  release: v0.17.0 — token usage attributed by phase, task, model and author

remote tags  … v0.16.0            v0.17.0, v0.18.0, v0.19.0 exist only locally
```

The published product is two releases and roughly 5,500 lines behind local. What is missing
from it is the entire cost-governance layer: `usage_ledger.py`, `meter-usage.py`, the report's
usage visualisations, the panel's Usage tab, cost bands, per-phase `budgetUSD`, and the gated
routing advisory. That layer is the strongest differentiator in the repository — §3 argues it
is the only part native Claude Code structurally cannot replicate — and no user has ever
seen it.

Related drift, same cause: `docs/index.html` is the GitHub Pages demo and the target of the
README's "▶ See it" link. It was generated 2026-07-23 and `grep 'id="usage"'` returns zero.
The hosted demo omits the flagship feature set. `examples/acme-store/acme-store-audit.html`
(generated 2026-08-06) has it.

### 1.2 What was built

| | |
|---|---|
| Tracked lines | 24,491 — 14,138 Python · 3,889 Markdown · 3,886 JSON · 2,126 HTML |
| Surface | 15 commands · 2 skills · 3 agents · 8 hooks · 2 JSON Schemas · 2 templates |
| Tests | **1011** runtime cases across 20 `--selftest` suites in CI, globbed rather than enumerated (675 across 17 before this work) |
| CI | 3 jobs · ubuntu + windows matrix · ajv draft-2020-12 · `claude plugin validate` |
| Runtime dependencies | 0 (stdlib-only, enforced as a hard rule in `CONTRIBUTING.md`) |
| Releases | 24, from v0.1.0 to v0.19.0, between 2026-07-06 and 2026-08-06 |

The largest single investment is the presentation layer: `panel-server.py` (2,998 lines) and
`render-report.py` (2,681) are 40% of all Python. That is worth noting because it is unusual
for a plugin, and because §7 argues the visual result does not yet reflect the investment.

### 1.3 What was distributed

| | |
|---|---|
| Stars / forks / open issues / issues ever | 1 / 0 / 0 / 0 |
| Traffic, 14 days to 2026-08-05 | 26 views, **4 unique visitors** (9 of 14 days: zero) |
| Repo topics | unset |
| README badges | none |
| Anthropic official directory | not listed |
| Third-party aggregators | absent from all checked (claudepluginhub, claudemarketplaces, claudeskills, claude-plugins.dev, claudedirectory) |
| External contributors | 0 |

**The diagnosis is that this is a distribution problem presenting as a product problem.**
The engineering is in the top decile of what ships as a Claude Code plugin. The visibility
is indistinguishable from not having published.

---

## 2. What the product actually is

A manifest-driven audit-and-fix orchestrator. The manifest (`docs/audit/audit-plan.json`,
JSON Schema draft 2020-12, 856 lines of schema) is the single source of truth; commands read
and mutate it; every mutation is re-validated referentially — unique ids, dependency cycles,
bidirectional `fileIndex`, reciprocal bug↔task links.

Around that sit four mechanisms:

1. **Eight deterministic hooks.** A plan gate that denies edits to files no `in_progress`
   task covers, two secret guards, a TDD reminder, a bash-write observer, a plan-skip
   detector, and a usage meter.
2. **Three agents with pinned tool lists.** `audit-explorer` has no `Edit`, `Write`, or
   `Bash` in its `tools:` frontmatter, so it is read-only as a property of the harness rather
   than as a request in a prompt. `audit-reviewer` cannot edit. Each returns strict JSON.
3. **Two artifact renderers.** A standalone HTML + Markdown report, and a localhost browser
   control panel — both vanilla, zero dependencies, zero network fetches.
4. **A token ledger.** `.claude/usage/<YYYY-MM>.jsonl`, append-only, one row per
   hour-bucket × dimension tuple, priced at write time so a later rate-table edit never
   rewrites history.

Plus: sharded manifest layout enabling parallel phases across git worktrees, two-tier locks
in `$(git rev-parse --git-common-dir)` so they coordinate across worktrees and never appear
in `git status`, an Azure DevOps work-item sync, and a headless CI gate.

---

## 3. Value against native Claude Code

Native has moved a long way since v0.1.0 shipped on 2026-07-06. Most of what this plugin
introduced now has some native counterpart. Being precise about where the overlap is real and
where it is superficial is the whole question, because the marketing claim has to survive a
reader who knows the native feature set.

| Native capability | What it covers | What it does not |
|---|---|---|
| Plan mode | A gate before edits; a plan file | Per-session and advisory. No persistent artifact bound to specific files; nothing carries across sessions |
| Hooks | The mechanism, fully | The policy. You write the logic |
| Subagents / Agent Teams | Parallel specialised agents | No tool-pinning discipline or structured JSON contract by default |
| `/review`, `/security-review`, `/code-review` | One-shot diff review | No sign-off ledger, no per-phase gate ordering, no record of who signed what |
| Checkpoints | Rollback | Rollback is not a gate |
| `/cost`, `/stats` | Session and subscription spend | Session-scoped totals |
| Native OpenTelemetry | `claude_code.cost.usage`, with attributes for `model`, `agent.name`, `skill.name`, `query_source` | **No attribution to plan units.** There is no phase, no task, no budget in the attribute set |
| Artifacts in Claude Code | Live shareable dashboards built from session context | Not deterministic, not a CI artifact, not reproducible from a committed file |
| TodoWrite / Tasks | In-session task tracking | Ephemeral; no schema, no validation, no history |

### What remains genuinely non-native

1. **Cross-session, file-scoped enforcement.** `require-plan.py` denies an edit to a file no
   `in_progress` task covers, in every session, with a single-use logged bypass. Native plan
   mode ends when the session ends.
2. **A durable, schema-validated plan artifact that survives context loss.** Native plan
   files are prose; `TodoWrite` is ephemeral. Neither is referentially validated.
3. **Spend attributed to plan units.** Native OTel can say "Sonnet, in the `audit-executor`
   agent, from a slash command." It cannot say "phase P2 has spent $4.10 of a $6.00 budget"
   or "task P2.3 is a three-attempt outlier for its risk band." Those require knowing what a
   phase and a task are, which means requiring a plan. **This is the real moat, and it is
   the part that is unpushed.**
4. **A CI gate that runs without Claude.** `audit-status.py --json --gate --fail-on` exits
   non-zero in a pipeline; the report renders headless as a build artifact. Most plugins in
   this space are interactive-only.
5. **Conflict-free parallelism.** Sharded manifest + git-common-dir locks + per-phase
   `claim` records, so two phases run from separate worktrees and merge without touching the
   same file. Nothing else in the ecosystem addresses this.
6. **Zero dependencies.** stdlib-only Python with a `python3 → python → py` launcher and a
   Windows CI leg. It installs where npm-based competitors do not.

Note the shape of that list: five of six items depend on the manifest existing. **The
manifest is the moat, not the hooks.** The hooks are the enforcement mechanism, and hooks are
native — anyone can write them. What nobody else has is a validated, durable plan that the
hooks, the agents, the report, the CI gate, and the cost ledger all read from.

---

## 4. Competitive landscape

Market shape as of mid-2026: the Anthropic official directory carried 256 entries on
2026-07-17 (36 first-party, 220 external), against roughly 9,000 third-party entries across
the wider ecosystem. Install counts from the public directory on 2026-06-01.

| Player | Reach | Approach | Read |
|---|---|---|---|
| **Frontend Design** (Anthropic) | 829,316 installs | First-party, design guidance | Different category; useful only as a ceiling reference |
| **Superpowers** (obra) | 752,120 installs | Skills that auto-trigger — `/brainstorm`, `/write-plan`, `/execute-plan`, TDD skills, worktrees | The direct competitor for mindshare. Persuasion, not enforcement. **Wins on distribution roughly 750,000:1** |
| **tdd-guard** (nizos) | Plugin + `probity` (Claude, Codex, Copilot CLI) | PreToolUse interception; validates TDD adherence by invoking **a separate Claude session**; JS/Python/PHP/Go/Rust | Closest competitor on enforcement, and deeper on TDD specifically. Costs tokens per validation. No plan artifact, no report, no cost tracking |
| **claude-night-market** (athola) | 23 plugins · 186 skills · 128 commands · 54 agents | `imbue` (TDD gates), `conserve` (destructive-command blockers), `leyline` (additive-bias audits), `pensive` (review), `spec-kit` | Overlaps on nearly every axis, at breadth rather than depth. The counter-position is this repo's own stated principle: *"3 excellent > 7 mediocre"* |
| **code-quality-tools** (camoa) | — | Five quality gates; installs and runs PHPStan/ESLint/Jest/Semgrep; PDF reports with SVG gauges | A tool runner, not an orchestrator. No durable plan |
| **claude-code-usage-dashboard** (agenticsec) | — | 90 MCP tools, 9 skills: daily cost, standup, team status | The closest thing to the usage layer — but calendar-and-session scoped, like native OTel |
| **spec-kit** (GitHub) | 80,000+ stars | SDD: organises artifacts | Outside the plugin system. Greenfield-leaning |
| **BMAD-METHOD** | 37,000+ stars | SDD: organises people — Analyst / PM / Architect / PO / Dev / QA personas | Greenfield, heavyweight. Reported ~31,700 tokens per workflow run and $800–2,000 per developer per month on frontier models. That reputation makes buyers wary of any multi-agent pipeline, including this one |

### Correction to a prior assumption

`TODO.local.md` records the competitive read as *"NIJEDAN SDD/TDD/audit plugin u zvaničnom
direktorijumu"* — no SDD/TDD/audit plugin in the official directory. **That is no longer
true.** The niche has occupants: `tdd-guard` on enforcement, `claude-night-market` on breadth,
`code-quality-tools` on gates, and Superpowers on the workflow that most people actually
adopt.

What is still unoccupied is the *combination*: mechanical enforcement, a durable
schema-validated plan, spend attributed to that plan, a shareable report, and conflict-free
parallelism. No competitor has more than two of the five. That is a narrower and more
defensible claim than "the niche is empty," and it has the advantage of being true.

### Where the positioning should sit

Brownfield. Spec-kit organises artifacts and BMAD organises people, both aimed at work that
starts from nothing. "Take an existing codebase, audit it, and grind it down phase by phase
with sign-off at each gate" is a different job, and it is the underserved half of the SDD
market. The product already does this — `/audit:init` exists to generate a plan *from* a
codebase — but nothing in the public positioning says so.

---

## 5. The enforcement decision

### 5.1 The problem

From `plugins/audit/README.md`:

> The six guard hooks activate in **every** project and session — before any manifest exists.
> That is the point (the guards are always-on), but it surprises people: in a repo with no
> audit manifest, the plan-first gate still allows only **one** small non-manifest-covered
> source file per session, then blocks the second with guidance.

The README is honest about this, and puts it above the fold, which is admirable. Honesty in
documentation does not prevent an uninstall. The first-run sequence for someone who installs
and does not immediately run `/audit:init` is: edit two files in an unrelated repo, get
denied.

### 5.2 Why this is a defect and not a trade-off

The usual framing is that some users dislike enforcement and the gate filters them out. That
framing is wrong, and it obscures the actual problem.

In a repo with no manifest, `require-plan.py` has no information about intent. There is no
plan to check the edit against. So it falls back to a heuristic — one small file per session,
then deny. **That is a default-deny on an empty policy.** The guard issues a decision with
no evidence.

This collides with the principle the rest of the product states repeatedly. From
`plugins/audit/README.md`:

> Every surface prints the thresholds it used, because "this task is an outlier" is a claim
> and a claim whose basis is invisible cannot be checked.

> On a well-routed project the output is silence, which is the correct answer rather than a gap.

The usage layer refuses to make a claim without evidence, and says so as a design value. The
plan gate issues its **strongest** claim — deny — on its **weakest** evidence — no plan at
all. Fixing that is not a softening of the thesis. It is the thesis applied consistently to
the one surface that currently exempts itself.

Three supporting arguments:

1. **Enforcement without a plan is not this product.** The product is plan-first development,
   mechanically enforced. In a repo with no manifest, plan-first development is not happening,
   so there is nothing to enforce. What the guard does in that state is rate-limit edits.
   That is a different and worse product sharing a code path.

2. **The deny is unfalsifiable to the person receiving it.** When P2.3 is `in_progress` and
   covers `src/auth.ts`, a deny on `src/cart.ts` is legible — you are outside your plan, and
   the fix is cheap. With no manifest, the message asks someone who has never run
   `/audit:init` to hand-author a schema-validated manifest, or to type `#no-plan`. Both
   exits cost more than the edit they wanted. **A guard whose cheapest exit is a bypass
   keyword trains people to reach for the bypass keyword** — and that erodes the guard
   everywhere, including where it is load-bearing.

3. **For a team rollout it converts into maintainer support load.** Every colleague who
   installs it and hits a deny in an unrelated repository becomes a question directed at
   whoever introduced it.

### 5.3 Recommendation: grade the gate by evidence

Not a binary warn/deny switch. Three states, keyed to how much the plugin actually knows:

| Repo state | Plan gate | Message |
|---|---|---|
| No manifest | **observe** — record what would have been blocked in `stateDir` | Once per session: `plan gate would have blocked 3 edits this session — run /audit:init to turn it on` |
| Manifest exists, no `in_progress` phase | **warn** | `src/cart.ts isn't covered by an in_progress task` |
| Manifest + `in_progress` phase | **deny** — full enforcement | The existing message, now legible, with a cheap exit |

This is the same design as the v0.19.0 routing advisory, which requires at least three prior
tasks by the cheaper model in the same risk band, in this repo, with no worse attempt rate,
clearing both a percentage and an absolute floor, before it says anything at all. The plugin
already knows how to gate a claim on its evidence. It does not yet apply that to its own gate.

The observe state is also better marketing than the deny. "I would have blocked 3 edits this
session" *demonstrates* the guard working; a deny *asserts* it. One earns the next step; the
other spends goodwill on a stranger.

**Do not grade the other hooks.** `guard-secrets-read.py` and `guard-edits.py` stay
deny-by-default. Reading `.env` is wrong whether or not a manifest exists — those guards do
not need a plan to be correct. Only the plan gate is graded, because only the plan gate is
making a claim about a plan.

**Escape hatch:** `"enforce": true` in `.claude/audit.config.json` restores always-on deny at
repo or user scope. The difference from today is that it becomes a decision someone made,
rather than a default that surprises someone who has not opted in.

**Marketing consequence.** The README's warning becomes a feature line: *enforced, once you
have a plan; observant before that.* The claim gets stronger by getting more precise, which
is the same move the CHANGELOG makes on every other feature.

---

## 6. SWOT

### Strengths

- **Enforcement is mechanical, not prompted.** Hooks deny; agent `tools:` lists omit
  `Edit`/`Write`/`Bash`. The claim is verifiable by reading frontmatter, which is rare in a
  market where most "enforcement" is a strongly-worded skill.
- **Zero runtime dependencies**, stdlib-only, with a Windows CI leg proving the interpreter
  fallback. Installs where npm-based competitors do not.
- **1011 runtime test cases across 20 suites in CI** (a static `check(` grep reads 686; the runtime count is the verifiable one), plus ajv schema validation, plus `claude plugin validate`, plus a
  determinism check that regenerates the demo ledger and diffs it against the committed copy.
- **Spend attributed to plan units** — not replicable by native OTel, as argued in §3.
- **The prose is publishable-grade.** "A claim whose basis is invisible cannot be checked."
  "Guardrails, not jails." "An unbudgeted phase is not a phase at zero." "On a well-routed
  project the output is silence." This is an asset most projects do not have.
- **It under-claims honestly.** `SECURITY.md` enumerates seven of its own accepted bypass
  classes with upstream issue references. The README has a *Repos without tests* section
  admitting `testGateGreen` passes vacuously with no runner — that the discipline "silently
  does nothing." Voluntary disclosure of your own failure modes is the cheapest trust you can
  buy and almost nobody spends it.
- **Real distributed-systems thinking** in the sharded layout, and it came from a written
  decision-support report (`docs/design/audit-concurrency-report.md`) anchored in an actual
  incident.
- **Dogfooded** — this repo's own roadmap is an `audit` manifest, CI-validated on every push.

### Weaknesses

- **Distribution is effectively zero** (§1.3), and **the flagship is unpushed** (§1.1).
- **The live demo is a month stale** and omits the usage feature entirely.
- **Global hooks on install** make the first run hostile (§5.1).
- **No `/audit:doctor`.** Nothing answers "is this working" before you hit a failure.
  Environment problems surface as prose in a Troubleshooting section.
- **No cheap first win.** The path to value runs through `/audit:init`, which interviews you
  and then spawns up to six agents. That is a real token cost demanded before any
  demonstrated benefit.
- **Nine of eleven commands rely on the model to format raw JSON.** `audit-status.py` prints
  indented JSON and `commands/status.md` instructs Claude how to lay it out. So output
  formatting is non-deterministic and costs tokens to re-narrate — precisely the failure that
  `commands/usage.md` was written to prevent for itself:
  > **Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**
  > … a usage tool that spends a pile of tokens laying out its own tables every time you ask
  > what you spent is self-defeating.

  The principle is correct and applied to exactly one command.
- **Confirmed defects**, §8.
- **Accessibility gaps**: the report emits no `<html>` element at all, so no `lang`; sortable
  columns are keyboard-inaccessible; no `aria-sort`; no `aria-pressed` on filter chips; the
  panel toast is not announced.
- **No visual identity.** The report reads as a Jira export (§7).
- **Screenshots are manually captured and stale** — `panel-guards.png` shows three tabs; the
  code has four.
- **Five duplicated sources of truth** for config defaults (`_config.DEFAULTS`, the docstring
  table, the README table, the example template, the panel `DESC` strings). Only two are
  machine-checked.
- **Bus factor 1.** Single author, zero external contributors, no funding.
- **Python + Git Bash on Windows** is a hard prerequisite.

### Opportunities

- **Official directory submission is one form.** External plugins are accepted with automated
  screening, and updates pushed to GitHub `main` are picked up automatically without
  re-submission. `claude plugin validate` already passes in CI.
- **Nobody ties spend to a plan, and native OTel structurally cannot** (§3). That is a wedge
  aimed at the engineering manager — the person who has both budget anxiety and authority.
- **The "enforcement over persuasion" essay already exists**, distributed across
  `CHANGELOG.md`, `SECURITY.md`, and the plugin README. It needs assembling, not writing. The
  upstream RFC being closed as "not planned" is the evidence that the niche was deliberately
  left to plugins.
- **Artifacts in Claude Code** make a shareable URL possible where today there is a `file://`
  path. That removes the single biggest friction on the product's best surface.
- **Brownfield is the underserved half of SDD** (§4).
- **The manifest is an audit trail** — signed-off phases, commit SHAs, reviewer findings,
  spend per phase. That is a compliance artifact, and the ADO sync to reach regulated teams
  already exists.

### Threats

- **Native convergence.** Plan mode, Agent Teams, checkpoints, `/security-review`, OTel cost
  attributes, and Artifacts dashboards all landed in the window this plugin was built. Each
  release narrows the gap, and the gap is now down to the six items in §3.
- **Superpowers' 752,120 installs is a default-choice moat.** Being the second workflow plugin
  someone installs is a much harder sell than being the first.
- **`commands/` versus `skills/` was evaluated on the wrong axis.** The ADR in
  `CONTRIBUTING.md` assesses deprecation risk and concludes NO-GO twice, with the revisit
  trigger set to "`commands/` deprecation only." But Superpowers wins on **auto-triggering**,
  and auto-triggering is a skills-only mechanism. That is a discoverability disadvantage
  today, not a risk that materialises later. The ADR's revisit trigger cannot fire on it,
  because it is not watching for it.
- **Aggregator absence compounds.** Five directories index this ecosystem and rank for the
  queries a prospective user types. Being in none of them is not neutral; it is a widening
  gap.
- **Cost perception.** `/audit:init` spawns up to six agents. BMAD's reputation
  ($800–2,000/dev/month) has primed buyers to be suspicious of multi-agent pipelines
  generally, and the product's own answer to that — the usage layer that would show the real
  number — is the unpushed part.
- **Bus factor 1 plus no funding** is a procurement objection for exactly the enterprise
  buyer the ADO sync targets.

---

## 7. UI/UX direction

### The problem in one sentence

The report is a competent, anonymous data table. For a product whose entire thesis is
*gates*, nothing in the visual language expresses a gate.

The subject is an audit that ends in a **signature**. The vernacular of that world is
inspection records, gate stamps, ledgers, sign-off sheets, chain of custody. The current
design borrows nothing from it. It borrows from Jira.

### Signature element: the gate rail

There is already a thin coloured bar to the left of each phase row (`[data-status]` driving
`--st`). Promote it to the spine of the page: a continuous vertical rail down the left of the
phase section, where each phase is a **gate on the line** — a closed gate drawn as a solid
crossbar, an open one as a break in the rail, a signed one stamped with its short SHA.

The rail should encode the readiness DAG — `blockedBy` and `dependsOn`. That information is
in the manifest, is what actually determines what you can work on next, and is **completely
invisible in the report today**. Structure carrying real information rather than decorating
it, and the one thing a Jira export cannot do.

### Fixes, in priority order

1. **Lead with the verdict, not the title.** The hero must answer "can I ship?" Today it is a
   title, a metadata line, and a progress bar that renders empty in every committed
   screenshot. Replace with gate state (how many phases signed off, how many blocked), the
   one ready task, and spend against budget.

2. **`READY NOW: P2.4` is the most actionable string on the page and currently the least
   prominent element on it** — bottom of the document, small, monospace, no affordance.
   Promote it and make it copyable as `/audit:run P2.4`.

3. **Cut the empty columns.** `MODEL`, `RISK`, `COMMIT`, `DONE`, `ADO`, `OUTCOME` are six of
   nine columns and all six are blank on phase rows. Collapse to four always-visible columns
   and move the rest into the expanded task detail. **Table density should follow the data,
   not the schema.**

4. **Give typography a point of view.** Keep the system stack for body text. But right now
   monospace is spent on metadata chrome — the least important text on the page — while the
   display role is plain bold system. Invert it: identifiers, SHAs, task ids, and money are
   the *content*, so set those in mono deliberately, and give phase titles a face with some
   character. The type is currently a neutral delivery vehicle; it should be part of what
   makes the artifact recognisable.

5. **Panel labels in human words.** `GUARDEDITS.TOKENVARS (NEVER LOGGED)` reads as a shouted
   JSON path because `h2{text-transform:uppercase}` is applied to raw key names. It should
   read "Secrets never written to logs", with the JSON key as small secondary text for
   whoever is editing the file directly.

6. **Truncate the project path** in the panel header with a middle ellipsis and a `title`
   attribute. `word-break:break-all` currently wraps a temp path across two lines in the
   header.

7. **Mobile: get prose out of the scrolling table.** Phase `desiredOutcome` sits in a
   `colspan=9` cell inside a `min-width:34rem` table under `overflow-x:auto`, so sentences
   clip mid-word and require horizontal scrolling to read.

---

## 8. Confirmed defects

All verified against the source on 2026-08-06. Each is reproducible from the cited line.

> **Correction (2026-08-06, after implementation).** This section originally attributed
> the empty progress bars to an entrance animation captured at t≈0. That was wrong, and
> the real cause is worse: the bar fill is an inline element, so it has never painted for
> anyone. The animation theory was disproved by measuring in a browser — the bars are
> 0px wide whether the animation runs or not, and the animation turned out not to be
> running at all because its easing token was corrupted by a missing semicolon. Three
> rows below replace the original one. The lesson is the section's own standard applied
> to itself: a plausible cause is not a verified one.

| Defect | Evidence | Consequence |
|---|---|---|
| **Per-phase task-status filter is unreachable** | `render-report.py:242` `tr.taskfilter{display:none}`; `:558` `tfRow.style.display = open ? '' : 'none'`. Setting `''` removes the inline declaration, so the stylesheet's `display:none` wins | The row, its label and its chips are emitted into every report and populated by JS at `:656–674`, and can never be seen. Fix: `'table-row'`. `tr.task` works only because it has no default `display` rule |
| **Report has no `<html>` element, therefore no `lang`** | `render-report.py:1829` starts at `<!doctype html>` then `<meta charset>`; confirmed in the generated `examples/acme-store/acme-store-audit.html` | Screen readers guess the language. The panel does have `<html lang=en>` (`panel-server.py:1012`), so the two surfaces disagree |
| **Sortable columns are keyboard-inaccessible** | `grep -c aria-sort` → 0. `<th>` carries `cursor:pointer` and a click handler, with no `role`, `tabindex`, or `aria-sort` | Keyboard and screen-reader users cannot sort, and cannot perceive sort state |
| **Filter chips have no pressed state** | `grep -c aria-pressed` → 0 | Which filter is active is conveyed by colour alone |
| **Progress bars have never painted** — corrected 2026-08-06, see note below | `.fill` is a `<span>` and its rule declared no `display`. An inline box ignores width and height, so the bar painted 0px wide at every percentage. The two bars that always worked (`.rank .track i`, `.bud .track i`) both declare `display:block` | **This is the README hero image**, showing 4/10 and a phase at 2/2 against blank tracks. Not a capture artifact — a product defect present since the v0.12.0 redesign, affecting every user's report |
| **`--ease` declared without a terminating semicolon** | Its value annexed the following comment block *and* the `--sp-0` declaration, making every `animation`/`transition` shorthand that referenced it invalid at computed-value time | All report animations and transitions were dead; `--sp-0` resolved to nothing. `_undeclared_css_vars` cannot see it — the annexed text still reads as `--sp-0:` to its regex |
| **`fillIn` and `fadeUp` declared only a `from` keyframe** while asking for `fill-mode: both` | Latent while `--ease` was broken. Once the easing token was repaired the animations ran, and the forwards fill pinned `.overall` and `.summary` at `opacity: 0` | The summary card rendered invisible — a defect the first fix activated rather than caused |
| **Port collision produces a raw traceback** | `panel-server.py:964` `ThreadingHTTPServer(("127.0.0.1", port), …)` with no `try`/`except`; the existing `try` wraps only `serve_forever()` | `/audit:panel --port 8080` on a taken port prints a Python `OSError` stack trace |
| **Panel session token is printed to stdout** | `panel-server.py:969` `print("audit control panel: %s" % url)`, where `url` embeds `?t=<token>` | The token lands in terminal scrollback and the Claude transcript. The pidfile holding the same token is gitignored with an explicit note; the printed copy is not addressed |

---

## 9. Roadmap

Ranked for credibility plus team rollout. Under a mass-adoption goal, T2 would precede T1.

### T0 — unblock (hours)

| # | Item | Rationale | Acceptance |
|---|---|---|---|
| 1 | `git push --follow-tags` | Everything else is downstream. The public product is two releases and ~5,500 lines behind | `origin/main` at v0.19.0; v0.17–v0.19 tags on the remote; CI green |
| 2 | Regenerate `docs/index.html`, and add a CI step that regenerates and diffs it | The live demo omits the flagship feature. Drift should be made impossible, not repaired | `grep 'id="usage"' docs/index.html` > 0; CI fails when stale |
| 3 | Playwright screenshot capture in CI | The hero image has empty bars; manual capture has already drifted a tab behind. Needs a committed large-manifest generator first — the panel shots' 50×20 fixture was never committed, which is why they could not be refreshed | Bars filled; `panel-*.png` show the Usage tab; capture asserts its own preconditions in CI |
| 4 | Repo topics + README badges (CI, version, licence) | Zero engineering, permanent visibility | Topics set; three badges rendering |

### T1 — first run and team rollout (days)

| # | Item | Rationale | Acceptance |
|---|---|---|---|
| 5 | **Evidence-graded plan gate** (observe / warn / deny) + `enforce: true` | §5. Removes the uninstall failure mode, applies the product's own principle consistently, and cuts maintainer support load during rollout | New selftest per state; README warning becomes a feature line |
| 6 | **`/audit:doctor`** | Nothing currently answers "is this working" before you hit a failure | Checks: interpreter reachable, git repo, config parses, `buildCommands` actually run, hooks firing, manifest valid, ledger writing |
| 7 | **A first win that costs nothing:** lead the quickstart with `/audit:usage --backfill` | It reads transcripts already on disk and shows the user *their own past spend, attributed*. No manifest, no agents, no token cost. `/audit:init` then becomes the obvious second step instead of the entry toll | README quickstart leads with it; `/audit:doctor` suggests it |
| 8 | Fix the seven defects in §8 | A dead feature, a broken hero image, and four accessibility gaps | Selftest asserting `display:table-row`; `<html lang>`; `aria-sort`/`aria-pressed`; `try`/`except` on bind; token withheld from stdout |

### T2 — the instrument (weeks)

| # | Item | Rationale |
|---|---|---|
| 9 | **Deterministic terminal rendering** for `status`, `next`, `phase` — move formatting into the Python that already computes the rollup and print it verbatim | Applies `commands/usage.md`'s own rule to the other nine commands. Cuts tokens and makes output consistent |
| 10 | **Budget as a gate, not a report** — warn at 80%, `AskUserQuestion` at 100% | `budgetUSD` already exists and is already rendered. "The only plugin that can stop a phase before it overspends" is a claim no competitor can make, and it extends the enforcement thesis into the cost dimension rather than bolting on a new one |
| 11 | **Report as a Claude Code Artifact**, alongside the local HTML | Removes the `file://` sharing wall and puts the product's best surface in front of people who never installed it |
| 12 | Official directory submission | `claude plugin validate` already passes; updates auto-propagate from `main` |

### T3 — positioning and identity

| # | Item | Rationale |
|---|---|---|
| 13 | Publish the "enforcement over persuasion" essay | The material exists across `CHANGELOG.md`, `SECURITY.md`, and the README. It needs assembling |
| 14 | Split the marketplace: `audit-guards` (hooks only) and `audit` (the orchestrator) | Two adoption ramps. Colleagues can take the guards without committing to the pipeline |
| 15 | Report visual identity (§7) | The presentation layer is 40% of the Python and does not yet look like it |
| 16 | **Re-evaluate `commands/` vs `skills/` on discoverability, not deprecation** | The ADR watches for the wrong signal (§6, Threats). A hybrid preserves the muscle memory: keep the commands, add thin skills that auto-trigger on "audit this codebase" and "what did that cost" |

---

## 10. Sources

Accessed 2026-08-06.

Install counts and directory size — Anthropic public plugin directory, 2026-06-01 and
2026-07-17 snapshots as reported by:
- https://designrevision.com/blog/best-claude-code-plugins
- https://composio.dev/content/top-claude-code-plugins
- https://claudecamp.ai/blog/claude-code-plugins-official-directory

Official directory mechanics and submission:
- https://github.com/anthropics/claude-plugins-official
- https://claude.com/docs/plugins/submit

Native capabilities:
- https://code.claude.com/docs/en/monitoring-usage
- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/artifacts
- https://claude.com/blog/artifacts-in-claude-code
- https://www.claudedirectory.org/blog/claude-code-plan-mode-guide
- https://www.developersdigest.tech/blog/claude-code-agent-teams-subagents-2026

Competitors:
- https://github.com/obra/superpowers
- https://github.com/nizos/tdd-guard · https://github.com/nizos/probity
- https://github.com/athola/claude-night-market
- https://www.claudepluginhub.com/plugins/camoa-code-quality-tools-code-quality-tools
- https://www.claudepluginhub.com/plugins/agenticsec-claude-code-usage-dashboard-plugin

SDD landscape:
- https://medium.com/@reenbit/bmad-vs-spec-kit-vs-openspec-choosing-your-spec-driven-ai-framework-in-2026-a6996b3ebb8d
- https://dev.to/willtorber/spec-kit-vs-bmad-vs-openspec-choosing-an-sdd-framework-in-2026-d3j
- https://www.thebcms.com/blog/spec-driven-development/

Repository facts are from this working tree at `521fbaf`, verified by `git`, `grep`, and
direct file reads. Traffic and stars are from the GitHub API for
`AleksandarBisevac/claude-plugins`.
