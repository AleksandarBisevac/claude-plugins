# Plans

Full briefs, kept **in the repository**. Open work and its status live in `../PLAN.md`; these
files are what you read before picking up a chunk.

They are here because of a failure worth naming. Claude Code writes plans to `~/.claude/plans/`,
outside the repo, invisible to every other machine, clone and session. On 2026-08-08 a plan of
~29 requirements across 16 chunks and four governance releases was written there, four chunks of
it were built, and then `docs/PLAN.md` was created from what was *in the repo* — so the other 25
requirements were simply absent. Nobody noticed until the user read `PLAN.md` and asked where they
had gone. Same failure as `TODO.local.md` being gitignored, one level up.

**The rule: copy a plan into `docs/plans/` before acting on it.**

Each file keeps its original body **verbatim** — a plan that quietly edits its own premises cannot
be checked against what actually happened — with a status block added on top, and any correction
to its reasoning stated as a correction rather than a silent rewrite.

| File | Covers | State |
|---|---|---|
| `2026-08-08-report-panel-ui-governance.md` | Report + panel UI/UX overhaul (A1–A11, B1–B16, C1–C2) and four governance releases (areas, journal, policy, help) | Report c1–c4 and Panel c1–c2 done; the rest open. `PLAN.md` item **U1** |
| `2026-07-29-per-phase-config-and-monorepo.md` | Per-phase `reviewSkill`, phase `area`, `/audit:worktree`, and a multi-manifest workspace | v0.16 (A/B/D) shipped; option C undecided. `PLAN.md` item **U2** |

Not every plan in `~/.claude/plans/` belongs here — most are for other repositories, and the ones
for this repo whose work fully shipped are recorded in `CHANGELOG.md` instead. Copy a plan in when
it has open items.
