---
description: 'Multi-agent codebase audit that GENERATES the audit manifest (phases/tasks) at manifestPath. Interviews you for scope/goals, fans out parallel read-only explorers, synthesizes findings into a schema-valid plan for /audit to execute.'
argument-hint: '[optional scope/goals — you will be interviewed for the rest]'
allowed-tools: Read, Write, Edit, Bash, Agent, Glob, Grep, AskUserQuestion
---

# /audit:init — generate the audit manifest

Produces the manifest that `/audit` executes. Generation is multi-agent: parallel
read-only explorers audit the codebase, the orchestrator (you) synthesizes their
findings into phases/tasks. **`$ARGUMENTS`** (free text) seeds the interview answers.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve
`manifestPath` from `.claude/audit.config.json` (default `docs/audit/audit-plan.json`).

## 1. Preflight

If a file already exists at `manifestPath`, ask the user (AskUserQuestion):
- **Abort** (default) — keep the existing manifest; suggest `/audit status`.
- **Regenerate** — back it up to `<manifestPath>.bak-<UTC timestamp>` first.
- **Append phases** — keep existing phases; new phases continue the id sequence.

## 2. Interview (BEFORE any exploration)

Merge `$ARGUMENTS` with answers to (ask only what `$ARGUMENTS` doesn't cover):
1. **Dimensions** (multi-select): security · correctness · test coverage · performance · architecture · DX/build health.
2. **Scope**: directories to include/exclude (default: whole repo minus vendored/generated code).
3. **Development branch** (default `main`) → `meta.developmentBranch`.
4. **Size appetite**: S (1–2 phases, quick wins) / M (3–4) / L (5+, thorough).
5. **Known pain points** — free text; explorers get these as priority hints.

## 3. Recon (orchestrator, read-only)

With Bash/Glob/Grep — never reading secrets:
1. Top-level layout, approx file count (`git ls-files | wc -l`), main languages.
2. Detect build/test/lint commands (package.json scripts, Makefile, pyproject, etc.)
   → draft `meta.buildCommands` (keys `lint`/`test`/`typecheck`/… mapping to real commands).
3. Split the included scope into 2–6 coherent **subsystems** (by directory/domain).

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
   phase a one-line `desiredOutcome` (what success looks like — `/audit` displays it and
   sign-off must address it). Respect the
   size appetite; overflow goes to `deferred.items` (with reasons) or `proposals`.
3. **Finding → task** using the conventions doc's new-task template. Rules:
   - Incorrect behavior (bug-like) → `tests.mode: "tdd"`, `expectRedFirst: true`,
     `tests.add` from `suggestedTests` (each must FAIL on current code).
   - Behavior-preserving change (refactor/hardening) → `"regression"`.
   - Config/docs/mechanical → `"gate-only"`.
   - `tests.gate`: entries resolving via the detected `meta.buildCommands` keys.
   - `model`: `haiku` for mechanical low-risk, `sonnet` default, your strongest tier for `risk: "high"`.
   - `files` from the finding; `blockedBy`/`dependsOn` only where a real ordering exists.
4. **Assemble the manifest**: `$schema` (the plugin schema URL), `meta`
   (`version: 2`, `repo` from `git remote get-url origin` or the directory name,
   `createdISO` from `date -u +%Y-%m-%dT%H:%M:%SZ`, `developmentBranch`, `branchPrefix: "audit"`,
   `commit`, detected `buildCommands`, defaults elsewhere), `phases`, top-level `fileIndex`
   built from every task's `files`, `bugs: []`, `deferred`, `proposals`.

## 6. Write + validate

1. `mkdir -p` the manifest's parent directory; Write the manifest.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>` —
   on findings, fix and re-run until clean (this is mandatory).
3. If `npx` is available, also run
   `npx ajv-cli validate --spec=draft2020 -s "${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json" -d <manifestPath>`;
   if npx is missing, skip silently.

## 7. Report

Print: per-phase table (`id — title — task count — dimensions covered`), total task count
by `tests.mode` and `risk`, what was deferred and why, any open questions for the human,
and the handoff: **next run `/audit status`, then `/audit phase P0`**.
