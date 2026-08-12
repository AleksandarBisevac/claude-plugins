---
description: 'Multi-agent codebase audit that GENERATES the audit manifest (phases/tasks) at manifestPath. Interviews you for scope/goals, fans out parallel read-only explorers, synthesizes findings, then presents the proposed phases for approval BEFORE writing — approve to materialize, or park them as proposals for later /audit:propose materialize.'
argument-hint: '[optional scope/goals — you will be interviewed for the rest]'
allowed-tools: Read, Write, Edit, Bash, Agent, Glob, Grep, AskUserQuestion
---

# /audit:init — generate the audit manifest

Produces the manifest that the `/audit:*` execution commands run. Generation is multi-agent: parallel
read-only explorers audit the codebase, the orchestrator (you) synthesizes their
findings into phases/tasks. **`$ARGUMENTS`** (free text) seeds the interview answers.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve
`manifestPath` from `.claude/audit.config.json` (default `docs/audit/audit-plan.json`).

## 1. Preflight

If a file already exists at `manifestPath`, first print any parked proposals it
carries (`proposals[]` entries with `status: "proposed"`):
`N parked proposal(s) — /audit:propose materialize <id>|--all` — the user may be
re-running init when what they actually want is to materialize what the last run
parked. Then ask (AskUserQuestion):
- **Abort** (default) — keep the existing manifest; suggest `/audit:status`.
- **Regenerate** — back it up to `<manifestPath>.bak-<UTC timestamp>` first
  (the backup includes any proposals).
- **Append phases** — keep existing phases; new phases continue the id sequence,
  counting BOTH live phases and any `proposals[].payload` reserved phase ids
  (see manifest-conventions.md → ID allocation). New proposal ids continue the
  `PROP-<n>` sequence the same way.

On **Regenerate** or **Append**, take the **concurrency lock** (see
`manifest-conventions.md` → Concurrency lock) BEFORE touching the file: refuse
while another session holds the index lock, so a generation never clobbers
an in-flight run, and hold it through write + validate (released in step 8).

## 2. Interview (BEFORE any exploration)

Merge `$ARGUMENTS` with answers to (ask only what `$ARGUMENTS` doesn't cover):
1. **Dimensions** (multi-select): security · correctness · test coverage · performance · architecture · DX/build health.
2. **Scope**: directories to include/exclude (default: whole repo minus vendored/generated code).
3. **Development branch** (default `main`) → `meta.developmentBranch`.
4. **Size appetite**: S (1–2 phases, quick wins) / M (3–4) / L (5+, thorough).
5. **Known pain points** — free text; explorers get these as priority hints.

**Areas (only if step 3.5 detected a workspace).** Ask this AFTER recon, not here — you cannot
propose areas you have not found yet. See step 3.5.

## 3. Recon (orchestrator, read-only)

With Bash/Glob/Grep — never reading secrets:
1. **Locate the git root.** Run `git rev-parse --show-toplevel`. If the project dir is NOT itself a
   git repo but a subdirectory is (common with a workspace in `test/`, `app/`, `packages/…`), record
   that subdir path (relative to the project dir) as **`meta.gitRoot`** (default `"."` when the project
   dir IS the git root). All git operations and gate commands will run there.
2. Top-level layout, approx file count (`git ls-files | wc -l`, run in the git root), main languages.
3. Detect build/test/lint commands (package.json scripts, Makefile, pyproject, etc.)
   → draft `meta.buildCommands` (keys `lint`/`test`/`typecheck`/… mapping to real commands). Commands
   run from the **project dir**, so when `meta.gitRoot` is not `.` **prefix each with `cd <gitRoot> && `**
   (e.g. `"lint": "cd test && npx nx run-many -t lint"`). This keeps each gate self-contained and
   independent of the caller's CWD.
4. Split the included scope into 2–6 coherent **subsystems** (by directory/domain).

### 3.5 Workspace detection (monorepo areas)

A repo holding several apps or packages wants `meta.areas` — a registry that gives each `area` tag a
root, a default sign-off reviewer and default executor skills. Detect it mechanically; do not guess
from directory names alone. Read only these files (all read-only, none is a secret):

| Signal | What to read | Areas it yields |
|---|---|---|
| `pnpm-workspace.yaml` | its `packages:` globs | one per matched package dir |
| `package.json` `workspaces` | array or `{packages: []}` | one per matched package dir |
| `turbo.json` / `nx.json` / `lerna.json` | presence + the package globs above | confirms a JS monorepo |
| `go.work` | its `use (...)` entries | one per module dir |
| `Cargo.toml` with `[workspace]` | its `members` | one per crate dir |
| `*.sln` | its `Project(...)` lines | one per project dir |

Expand globs with Glob and keep directories that actually exist. Cap the proposal at **8 areas**; if
there are more, propose the 8 with the most files and say how many were left out — a silent cap
would read as "that is all of them".

**If nothing matches, skip the rest of this step entirely and never mention areas again.** A
single-app repo must come out byte-identical to what earlier versions produced: no `meta.areas` key,
no `area` tags, nothing to explain.

If something matched, ask (AskUserQuestion, multi-select, all detected areas pre-selected):

- **Which of these should the audit track as areas?** — one option per detected workspace, labelled
  `<tag> — <root>`. Deselecting one is normal: vendored, generated and archived packages are exactly
  what this list will surface.
- Then, per selected area, ask only what you cannot detect: an optional **review skill** (default
  none — `meta.reviewSkill` applies) and optional **area skills** (default none). Offer the skills
  discovered in `.claude/skills/` and `~/.claude/skills/`; do not invent names.

Derive each `tag` from the package/module name, lowercased, non-alphanumerics collapsed to `-`
(`@acme/mobile-app` → `mobile-app`). Roots are **project-dir-relative**, like `task.files`.

## 4. Fan-out (multi-agent)

Spawn the plugin's explorer agents (`Agent` tool, `subagent_type: "audit:audit-explorer"`)
**in ONE message** (they run in parallel). The agent is **mechanically read-only** — its
tool list has no Edit/Write/Bash — and its system prompt already carries the hard rules and
the JSON return format; if the agent type is unavailable (older Claude Code), fall back to
general-purpose subagents and restate those rules inline.
Shard = subsystem × selected dimensions, **capped at 6 agents** (merge shards when over).
Every prompt must include:
- The subsystem's directories, the dimensions to audit, the user's pain-point hints.
- **Hard rules** (restated even though the agent knows them): read-only; NEVER read secret
  files (`.env`, credentials, keys) — names only; skip vendored/generated code.
- **Return format**: ONLY a JSON array of findings, each
  `{"title", "category", "severity": "low|med|high", "files": ["path[:lines]"], "evidence", "suggestedFix", "suggestedTests": [".."], "risk": "low|med|high"}`.

Parse each result; findings that don't parse as JSON get one retry prompt, then are dropped (report the drop).

## 5. Synthesis (orchestrator)

1. **Dedupe** findings by file + title similarity; keep the higher severity.
2. **Group into phases**: `P0` = build/test health + safety blockers (anything that gates
   verification of later work), then thematic phases by dimension/subsystem. Give every
   phase a one-line `desiredOutcome` (what success looks like — `/audit:status` displays it and
   sign-off must address it). Respect the
   size appetite; overflow goes to `deferred.items` (with reasons) or is parked
   directly in `proposals[]` as a full payload (step 6's park format) so it stays
   materializable.
   **Tag each phase** with the `area` tag(s) whose root(s) its tasks' files fall under — a list when
   the phase spans two, in the order you want them to resolve (written order decides the reviewer
   and the skill order). Skip entirely when step 3.5 found no workspace.
3. **Finding → task** using the conventions doc's new-task template. Rules:
   - Incorrect behavior (bug-like) → `tests.mode: "tdd"`, `expectRedFirst: true`,
     `tests.add` from `suggestedTests` (each must FAIL on current code).
   - Behavior-preserving change (refactor/hardening) → `"regression"`.
   - Config/docs/mechanical → `"gate-only"`.
   - `tests.gate`: entries resolving via the detected `meta.buildCommands` keys.
   - `model`: `sonnet` is the floor for ALL fix work (low/med risk, mechanical included);
     escalate to your strongest tier (`opus`) for `risk: "high"`. Do NOT route audit-fix tasks to
     `haiku` — a botched cheap attempt burns retries (`maxAttempts`) plus a reviewer round, costing
     more than one clean `sonnet` pass.
   - `files` from the finding; `blockedBy`/`dependsOn` only where a real ordering exists.
     **Never route a task at files inside a git submodule** (paths under a `.gitmodules` entry):
     the orchestrator commits from the parent repo and cannot stage submodule-internal files. If a
     finding lands inside a submodule, either scope a SEPARATE manifest with `meta.gitRoot` set to
     that submodule, or record it in `deferred` with the reason — do not put it in a parent task.
4. **Assemble the CANDIDATE manifest in memory — do not write yet**: `$schema` (the plugin
   schema URL), `meta`
   (`version: 2`, `repo` from `git remote get-url origin` or the directory name,
   `createdISO` from `date -u +%Y-%m-%dT%H:%M:%SZ`, `developmentBranch`, `branchPrefix: "audit"`,
   `gitRoot` (from step 3.1), `commit`, detected `buildCommands`, `areas` (from step 3.5 — omit the
   key entirely when nothing was detected or the user selected nothing), defaults elsewhere), `phases`,
   top-level `fileIndex` built from every task's `files`, `bugs: []`, `deferred`, `proposals`.
   Task `files` and `fileIndex` keys are **project-dir-relative** (they include the `gitRoot` prefix,
   e.g. `test/src/foo.ts` when `gitRoot` is `test`). When `gitRoot` is not `.`, prefer writing the
   manifest INSIDE the git root (set `manifestPath` accordingly, e.g. `test/docs/audit/audit-plan.json`,
   and mirror `gitRoot` into `.claude/audit.config.json`) so the orchestrator can commit its status
   history; note this to the user.

## 6. Present & approve (the gate)

Nothing synthesized has touched disk yet. Print the proposed plan, plain ASCII:

```
Proposed plan — 4 phases, 23 tasks (size appetite: M)

  id  title                 goal (desiredOutcome)               tasks  key tasks
  P0  Build & test health   CI green; test gate runnable        5      fix tsconfig; un-skip auth suite
  P1  Security hardening    no high-risk injection paths        7      parameterize SQL in orders
  ...
  deferred: 3 item(s) (reasons below) - open questions: 2
```

"Key tasks" = the 2–3 highest-risk task titles per phase. Then ask ONE
AskUserQuestion:

1. **Materialize all N phases** (Recommended) — write the manifest exactly as
   assembled; this is the pre-gate behavior.
2. **Park all as proposals** — the manifest gets `meta` + `phases: []` +
   `fileIndex: {}`; every synthesized phase is parked in `proposals[]` for later
   `/audit:propose materialize`. Nothing is lost; nothing starts until asked.
   The right answer for a team adopting the plugin mid-project that wants the
   analysis without the plan taking over.
3. **Choose per phase** — follow-up AskUserQuestion calls, one
   Materialize/Park choice per phase, at most 4 phases per call. Then apply the
   **dependency-closure rule**: materializing a phase auto-includes every phase
   it is `blockedBy`-linked to, and you announce each auto-include ("P1 pulls in
   P0 — P1 is blockedBy P0").

If the gate is aborted or goes unanswered, **park all** — conservative and
lossless: nothing is materialized without approval, nothing synthesized is lost.

Each parked phase becomes one proposal (see manifest-conventions.md → Proposals):

```json
{"id": "PROP-1", "name": "<phase title>", "status": "proposed",
 "origin": "audit:init", "createdISO": "<UTC now>",
 "scope": "<the phase's main dirs>", "benefit": "<desiredOutcome>",
 "openQuestions": [], "materializedAs": null, "materializedAt": null,
 "payload": {"phase": { ...the full phase, tasks fully initialized... }}}
```

The payload keeps its synthesized phase id (`P1`, …) — the id is **reserved**
(allocation counts it), so inter-proposal `blockedBy` refs stay meaningful and
materialization is a move, not a rebuild. `fileIndex` entries for parked tasks
are NOT written — the index covers live tasks only; materialize derives them
from `payload.phase.tasks[].files`.

## 7. Write + validate

1. `mkdir -p` the manifest's parent directory; Write the manifest as decided in
   step 6 (approved phases in `phases[]` with their `fileIndex` entries; parked
   phases in `proposals[]`).
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>` —
   on findings, fix and re-run until clean (this is mandatory).
3. If `npx` is available, also run
   `npx ajv-cli validate --spec=draft2020 -s "${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json" -d <manifestPath>`;
   if npx is missing, skip silently.

## 8. Report

**Materialized (fully or partly):** per-phase table (`id — title — task count —
dimensions covered`), total task count by `tests.mode` and `risk`, what was
deferred and why, any open questions for the human, and the handoff: **next run
`/audit:status`, then `/audit:phase P0`**.

**Parked (any):** a proposal table (`PROP-id — reserved phase — title — tasks`)
and the handoff: `/audit:propose list`, then
`/audit:propose materialize <id>|--all`. Add one note when everything was
parked: *the plan gate stays in its advisory (warn) tier until a phase is
materialized and running — same as any idle manifest; with `enforce: true` an
empty-phases manifest denies out-of-plan edits (its fileIndex is empty), so
materialize a phase before starting fix work.*

When areas were registered, list them (`tag — root — reviewer`) and say which phases carry which
tag; `/audit:doctor` will warn about any root that is not a directory.
Release the concurrency lock if you acquired one in step 1.
