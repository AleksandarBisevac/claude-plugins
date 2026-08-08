<!-- Recovered 2026-08-08 from ~/.claude/plans/. Body verbatim as written 2026-07-29. -->

# Per-phase config + monorepo ergonomics (v0.16 → v0.17) — the plan, as written

**Status, verified against the tree on 2026-08-08.** Everything in **v0.16 shipped**:
`phase.reviewSkill` is in the schema and `KNOWN_PHASE` (A), `phase.area` is in the schema with an
`areas` grouping in `audit-status.py` and an area column in the report (B), and
`commands/worktree.md` exists (D).

**v0.17's option C — the multi-manifest workspace — did not ship, and was never decided.** See
`docs/PLAN.md` item **U2**. The plan itself set the decision criterion, which is why this is an
open *question* and not an open *task*: *"whether A+B already covers most monorepos, leaving C
truly only for separate-git-repo teams. Decide after dogfooding A/B on a synthetic monorepo."*
That dogfooding has not happened. Note that the 2026-08-08 plan's **v0.28 `meta.areas` registry**
is a richer successor to B and pushes further down the one-manifest road, which is evidence for
answering C with "not needed" — but it is evidence, not the decision.

---

# Roadmap: richer per-phase config + monorepo/multi-team ergonomics (v0.16.0 → v0.17.0)

## Context

Scenario analysis (small→monorepo→subrepos, single→multi-dev/team) surfaced that the plugin already
handles per-**task** skills/model and per-**app** build/test (via `buildCommands` keys), but strains on:
the **review skill is global** (`meta.reviewSkill` — can't review BE vs mobile differently), there's
**no phase area/team tag** (no grouping/filtering/routing), **no cross-subrepo rollup**, and the
**parallel-run worktree setup is manual friction**. Chosen directions: **A + B + C + D**, with target
"all shapes equally" → sequence the small broadly-useful wins first, the big isolation feature last.

Prerequisite: this is the NEXT roadmap — do it **after** v0.15.0 is live-verified (shakedown) and released.
All of it rides the existing back-compat seam (dual-read loader, schema `additionalProperties:true`,
`audit-status` as the single aggregator) so single-file/legacy manifests keep working untouched.

---

## v0.16.0 — A + B + D (small, additive, help every scenario)

### A · Per-phase review skill (+ resolution fallback)
Fix the sharpest monorepo gap: let a phase pick its own reviewer.
- **`schema/audit-plan.schema.json`** — add optional `reviewSkill` (`string|null`) to `$defs/phase`.
- **`reference/orchestrator.md`** sign-off (~line 265) — resolve `reviewSkill = phase.reviewSkill ?? meta.reviewSkill`; everything else (reviewer agent, `phase.review.model`) unchanged. Update `reference/manifest-conventions.md` "New phase template" to mention the optional field.
- **`scripts/validate-manifest.py`** — add `reviewSkill` to `KNOWN_PHASE`.
- (Per-app build/test already works via `buildCommands` keys; per-phase `gitRoot` intentionally **out** — a monorepo is one git repo, and per-phase gitRoot invites footguns.)
- **Test:** selftest — a phase with `reviewSkill` resolves to it, a phase without falls back to `meta.reviewSkill`; validate stays clean with the new key. Harness: a 2-phase fixture with different `reviewSkill`s.

### B · Phase `area`/`team` tag (grouping · filtering · routing)
- **schema** — add optional `area` (`string`, free text: "backend"/"mobile"/"web") to `$defs/phase`.
- **`scripts/audit-status.py`** `rollup()` — include `area` in each phase entry; add an `areas` grouping (counts per area) to the summary.
- **`scripts/render-report.py`** — show an `area` column and allow grouping/filtering by it (the report already has phase filters).
- **`scripts/panel-server.py`** — surface `area` in the Composition/Overview views (filter chip, like the status chips).
- **validate** — add `area` to `KNOWN_PHASE`.
- **Test:** rollup exposes `area` + `areas` grouping; report/panel render + filter by area; selftest cases.
- Pairs with A: "review routing by area" = set each area's phases' `reviewSkill` (manual, explicit) — B makes the areas legible; no magic auto-routing.

### D · `/audit:worktree <phaseId>` helper (removes the parallel-run friction)
- **new `commands/worktree.md`** — `/audit:worktree <phaseId> [--remove]`: derive the branch name with the same slug rule as phase entry (`<branchPrefix>/<phaseId-lc>-<slug>`), run the pre-approved `git -C <gitRoot> worktree add ../<repo>-<phaseId> -b <branch> <developmentBranch>`, then print the exact `cd <path> && claude` line + "then run `/audit:phase <phaseId>` there". `--remove` cleans it up (`git worktree remove`). Read-mostly: only pre-approved branch/worktree ops; never edits the manifest.
- **docs** — `plugin.json` + `marketplace.json` command list, plugin README Commands table + the "Sharded layout — parallel phases" section (replace the manual `git worktree add` recipe with the helper).
- **Test:** the command creates a worktree on the correct branch off `developmentBranch`; `--remove` cleans it; documented. (Prose command → verify via a scripted dry-run of the git ops in a sandbox.)

**Ship:** one `feat/per-phase-config-v0.16` branch (or a PR per A/B/D), version bump 0.16.0 + CHANGELOG + tag.

---

## v0.17.0 — C · Multi-manifest workspace + cross rollup (design; refine after A/B land)

For scenario 4 (separate subrepos/teams/tech, independent cadence) where one manifest doesn't fit and
the submodule preflight forbids one audit spanning repos. **Design outline (to firm up post-v0.16.0):**
- A **workspace descriptor** — `.claude/audit-workspace.json` listing member manifests (paths, each with its own `meta`/gitRoot/reviewSkill), or `config.manifests: [...]`.
- **`scripts/audit-status.py`** — extend the aggregator (already the single source of truth) to iterate members and emit a **combined** rollup (per-manifest sections + a workspace total). `render-report.py` gains a workspace report.
- **new `commands/workspace.md`** — `/audit:workspace status|report` rolling up across members.
- Back-compat: single-manifest unchanged; workspace is opt-in.
- **Open question to settle first:** whether A+B (one rich manifest with `area`-tagged phases + per-phase `reviewSkill`) already covers most monorepos, leaving C truly only for *separate-git-repo* teams. Decide after dogfooding A/B on a synthetic monorepo.

---

## Sequencing & rationale
1. **Finish v0.15.0** (shakedown → release) — prerequisite.
2. **v0.16.0 = A → B → D** — each small, back-compat, broadly useful; A fixes the sharpest gap, B makes monorepos legible, D removes the friction you just hit.
3. **v0.17.0 = C** — only after A/B show whether one-rich-manifest suffices; C is the heavier separate-repos answer.

## Verification
- Per-feature `--selftest` cases on **both** manifest layouts (per-phase reviewSkill resolution; area grouping in rollup; worktree branch derivation).
- Dogfood A+B on a **synthetic monorepo fixture** (backend+mobile+web phases, different `reviewSkill`s + `area`s) — status/report/panel group by area, each phase signs off with its own reviewer.
- D: create+remove a worktree in a sandbox, confirm branch off `developmentBranch`.
- C (when built): a two-manifest workspace rollup equals the sum of the members.
- `claude plugin validate` ✔; legacy single-file manifests validate unchanged.

## Notes
- Pure roadmap — no code yet. On approval I'll turn v0.16.0 (A/B/D) into a tracked backlog in `TODO.local.md`
  (like the v0.15.0 flow: each task descriptive, with a test + result) and execute sequentially.
- No commit/push without asking; UI touches (panel area filter) get a green-light screenshot before PR.
- v0.15.0 shakedown/release still comes first unless you want to interleave.
