---
description: 'Multi-agent codebase audit that GENERATES the audit manifest (phases/tasks) at manifestPath. Interviews you for scope/goals, fans out parallel read-only explorers, synthesizes findings, then presents the proposed phases for approval BEFORE writing — approve to materialize, or park them as proposals for later /audit:propose materialize. Asks which manifest layout to write (one file, the default, or one file per phase for parallel worktrees).'
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
1. **Dimensions** (multi-select, and ALL SIX are offered): security · correctness ·
   test coverage · performance · architecture · DX/build health.

   **Ask them as TWO questions inside ONE `AskUserQuestion` call** — that tool takes at most
   four options per question, and six do not fit. This is not cosmetic. Asked as one question
   the last two are cut, and the only route left to them is typing their exact name into the
   automatic "Other" field, so a reader who has never opened this file cannot know they exist.
   That is the silent cap this command forbids for areas further down — *"a silent cap would
   read as 'that is all of them'"* — applied to its own list first.
2. **Scope**: directories to include/exclude (default: whole repo minus vendored/generated code).
3. **Development branch** (default `main`) → `meta.developmentBranch`.
4. **Known pain points** — **free text. Never a list you synthesize.**

   This is asked BEFORE recon, so the only material options could come from is documentation
   already in context — and documentation is the thing most likely to describe a state the code
   has left. Observed on a real repo: the docs still named a `pages/` layout a refactor had
   replaced outright, so every option offered pointed at files that no longer existed, and the
   wrong labels then travelled into six explorers as priority hints.

   Whatever the user types is a **hint, not a fact**. An explorer that cannot confirm a hint
   says so, and never restates it as a finding.

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

   **A GATE MUST NOT WRITE, and a detected command cannot be assumed read-only (F193).** These
   are read off the repo, which is a real strength and also means the candidate may be
   fix-in-place. Measured: `lint` was drafted as `pre-commit run --all-files`; `isort` and
   `black` rewrote five source files and reported `Passed` *because* they had, and a
   documentation task would have carried +33/−62 of backend reformatting into its commit.

   So for each candidate, **prefer the read-only spelling where one exists** and say which you
   chose: `prettier --check` over `--write`, `ruff check` over `ruff --fix`, `black --check`
   over `black`. Where a candidate may write and has no read-only twin — `pre-commit run`
   without `--files`, anything carrying `--fix`, `--write`, `--in-place` — **note that beside it
   in the proposal** so the human approving the manifest is approving a gate that may mutate,
   not discovering it later. A gate is a measurement; one with side effects has answered a
   different question than the one asked.

   `run-test-gate.py` catches it at run time regardless — but a gate the operator was never
   told about is a surprise the first time a phase signs off, and this is the cheaper place to
   say it.

   **And record HOW the test command can be pointed at paths.** It is the only input a task's
   own gate can be derived from (step 5.3), and nothing later in the run can recover it. Beside
   each `test`-family command, note which one the runner offers: a **source→test** mode
   (`jest --findRelatedTests <paths>`, `vitest related <paths>`), **test paths only**
   (`pytest <paths>`, `mocha <paths>`), a **project or package selector**
   (`jest --selectProjects <p>`, `go test ./<pkg>/...`, `cargo test --package <c>`,
   `dotnet test <project>`), or **nothing path-scoped at all** — a composite script such as
   `make check` or `npm run ci`, whose inside you cannot see from out here.

   Read the spelling off what the repo actually pins — the manifest that declares the runner,
   its lockfile, the config file it loads — and not off a memory of that tool's CLI: a flag
   that does not exist in the pinned version turns every task gate into exit 2. And
   **"nothing path-scoped" is a finding to carry forward, never a gap to fill with a
   plausible-looking flag**; step 5.3 writes the wide gate and the reason when it reads that.
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
  none — `meta.reviewSkill` applies) and optional **area skills** (default none). Do not scan the
  filesystem for skills yourself — use the same ONE mechanical source step 6.1 uses: no manifest
  exists yet at this step, so write a stub to a temp file (`mktemp`; content
  `{"meta": {"version": 2}, "phases": []}`), run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <tmpfile> --json --discovery`, delete
  the temp file, and offer names from `discovery.skills` only — never invented ones. A
  `discovery.error` key means the scan failed and the list is empty (fail-open): say so and skip
  skill offers rather than guessing.

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
  `{"title", "category", "severity": "low|med|high", "files": ["path[:lines]"], "coupledPaths": [{"path", "shared"}], "coveringTests": [{"path", "covers"}], "evidence", "suggestedFix", "suggestedTests": [".."], "risk": "low|med|high"}`.
- **Coupling**: `coupledPaths` is what else is on the same data path as the files a finding
  names — another module reading or writing the same store, the other side of the same
  request/response or event shape, another file built from the same schema or generated type.
  Each entry names the path AND the store, shape or type both sides touch; an entry that
  cannot name what is shared is not a coupled path but a hunch, and `[]` is the answer when
  there is none, so silence never doubles as absence.
- **Existing coverage**: `coveringTests` is which test files ALREADY exercise the files a
  finding names, each entry naming the path AND the function, endpoint or behaviour under
  test that the case drives — opened and read, never inferred from a filename that resembles
  a source file. This is what step 5.3 narrows a task's gate from, so `[]` is load-bearing
  rather than a shrug: looked and found none means the gate stays wide and the task records
  why, which is a different outcome from having not looked.

Parse each result; findings that don't parse as JSON get one retry prompt, then are dropped (report the drop).

## 5. Synthesis (orchestrator)

1. **Dedupe** findings by file + title similarity; keep the higher severity.
2. **Group into phases**: `P0` = build/test health + safety blockers (anything that gates
   verification of later work), then thematic phases by dimension/subsystem. Give every
   phase a one-line `desiredOutcome` (what success looks like — `/audit:status` displays it and
   sign-off must address it).

   **Gate coverage is a hard requirement, not a splitting rule.** Every phase's `testGate`
   must be able to prove THAT PHASE done: a phase tagged with two areas carries one entry per
   area, or states why a single command covers both. A gate that can be green while half the
   phase is unverified is decoration.

   **And narrowing a task's gate never narrows the phase's.** Step 5.3 derives each task's
   `tests.gate` from the files that task touches, which is a smaller claim about a smaller
   diff. This requirement is unaffected: the phase's `testGate` still has to prove every file
   every task under it touched, together. Two levels, two questions — a phase's coverage is
   not discharged by the tasks below it carrying gates of their own, however many are green.

   **The gate never forces a merge.** It is a LOWER bound on splitting - it tells you when you
   must split, never that you must join. Several distinct concerns can share one gate and stay
   separate phases: all Python work may be proven by the same `pytest -q`, while token flow,
   test coverage and a hand-maintained SQL whitelist remain three phases with three risks and
   three reviewers.

   **What decides the boundary is the `desiredOutcome`.** If two pieces of work cannot share one
   honest one-line outcome that sign-off can address, they are two phases - and a phase whose
   outcome cannot be written in a line is already too big.

   There is deliberately NO target number: the count follows the material (how many distinct
   outcomes it carries, with gate coverage as the floor), not a preference. Asking for a size up
   front turned that into a quota the plan was squeezed to fit. Two phases whose gate AND
   `desiredOutcome` are indistinguishable are one phase. Overflow is parked at the gate in
   step 6, recorded in `deferred.items` with its reason, or placed in `proposals[]` as a full
   payload (step 6's park format) so it stays materializable.
   **Tag each phase** with the `area` tag(s) whose root(s) its tasks' files fall under — a list when
   the phase spans two, in the order you want them to resolve (written order decides the reviewer
   and the skill order). Skip entirely when step 3.5 found no workspace.
3. **Finding → task** using the conventions doc's new-task template. Rules:
   - Incorrect behavior (bug-like) → `tests.mode: "tdd"`, `expectRedFirst: true`,
     `tests.add` from `suggestedTests` (each must FAIL on current code), **each
     entry opening with the repo-relative path of the file the case will live in**:
     `"<testFile>: <what it asserts>"`. That leading path is what joins the task's
     `files` and the `fileIndex`, so an entry that opens with prose leaves the case
     file outside the scope commit-scope grades the work against, and the validator
     warns (a finding from 3.0.0). The explorer's `suggestedTests` are prose, so
     this is a step YOU perform rather than a value you copy.
   - Behavior-preserving change (refactor/hardening) → `"regression"`.
   - Config/docs/mechanical → `"gate-only"`.
   - **`tests.gate` — and a task gate is not a small phase gate.** A **phase** gate asks
     *is the repository still whole*: it runs once, at sign-off, over everything the phase's
     tasks touched together, and it is the only thing that can catch the interaction no single
     task could see. A **task** gate asks *did this one change do what it was asked to*: it
     runs on every attempt, inside the executor's loop, and the only failure it has to be able
     to produce is one this task's own diff caused. So the phase gate is wide because its
     question is wide, and a task gate is narrowed to the task's own files — a wider one does
     not answer its question any better, it answers the PHASE's question again, once per
     attempt, per task, per phase running in parallel.

     **The wide default is the one that has been measured going wrong.** Handing every task
     the full suite meant a repo running two phases at once spawned a whole worker fan-out per
     task; on a suite that boots a database per worker the machine ran out of cores, and
     suites began failing for reasons no diff explained — red gates against tasks whose code
     was fine, and a retry burned on each. Nothing had guessed wrong. The plan had asked for
     it, on every task, because this line used to say only that gate entries resolve via
     `meta.buildCommands`.

     **Derive it from the task, or say you could not.** The inputs are the task's `files`, the
     `coveringTests` the finding reported, and the paths in `tests.add` — never a feel for what
     the change touches. Which one you use is decided by the path-scoped spelling recon
     recorded in step 3.3:
     - a **source→test** mode → that mode over the task's `files`. Prefer it wherever it
       exists: the runner maps sources to suites off the real import graph, which beats
       anything you or the explorer could infer from a tree.
     - **test paths only** → the `coveringTests` paths, plus every `tests.add` path.
     - a **project/package selector** → the one project the task's files sit in, resolved
       against a REGISTERED boundary (`meta.areas[tag].root`, a workspace member, a package
       directory) and never against a directory name that merely looks like one.
     - **nothing path-scoped** → the wide entry, and a reason.

     Entries still resolve via `meta.buildCommands` wherever the scope is shared, which is what
     gives a step a short name in the report instead of a long command printed twice. A scope
     that differs per task cannot be a shared key, so those entries are literal commands; that
     is the one place in a plan where a literal is the right shape, because what the row then
     says is the scope.

     **Nothing persists the spelling except the gates themselves, and that is enough.** A plan
     whose task gates are path-scoped carries the runner's own path-scoped form in every one of
     them, so a task added later (`/audit:task add`) reads the shape off its siblings instead of
     re-detecting it. A plan whose task gates are all the wide key carries no such record —
     which is the other thing the old default cost, and the reason it survived so long.

     **Two invariants, and the quiet one is second.** The derived gate must contain every
     `tests.add` path this task promises to author — a task whose own gate never runs the case
     it just wrote has bought a green with nothing behind it. And it must not narrow the
     phase's `testGate`, which step 5.2 states from the other side.

     **When it cannot be derived, the wide entry IS the answer** — a runner with no path-scoped
     spelling, files under no registered project, a finding whose `coveringTests` came back
     `[]` with no `tests.add` to stand in for them. Write the wide entry and put the reason in
     the task's `description`, naming what was missing. Do not narrow on a resemblance: a false
     red is noticed the same day and a false green is never noticed at all, so a guess here is
     the strictly worse trade even when it would usually be right.
   - `model`: `sonnet` is the floor for ALL fix work (low/med risk, mechanical included);
     escalate to your strongest tier (`opus`) for `risk: "high"`. Do NOT route audit-fix tasks to
     `haiku` — a botched cheap attempt burns retries (`maxAttempts`) plus a reviewer round, costing
     more than one clean `sonnet` pass.
   - `files` from the finding, **plus every `coupledPaths` entry the fix would leave wrong**;
     `blockedBy`/`dependsOn` only where a real ordering exists.

     **Say what shares this file's data path, not only what the finding named.** One question,
     asked once per coupled path: *if the executor makes this change and never opens that file,
     is that file now wrong?* The sibling that writes the column this fix renames, the client
     that parses the response field this fix drops, the caller built from the type this fix
     regenerates — each is wrong the moment the fix lands, so each is this task's work and
     belongs in `files`. A file that merely reads the same store through a shape the fix does
     not touch is context, not work: name it in the task `description` as something to check
     and leave it out. On a live phase, two of the three sign-off findings were the same shape
     — a sibling on a data path no task's `files` covered — and once a phase is `in_progress`
     the plan gate refuses that edit even to an executor that spots the sibling for itself: a
     subagent is told to stop and report, never to widen its own scope.

     **The other direction is not the safe one.** `files` is the plan gate's entire definition
     of a task's scope, so a task that claims everything sharing a data path with its own files
     has the codebase as its scope and the gate then permits every edit and guards nothing.
     A coupled path that is real work but not THIS task's work is a separate task with
     `dependsOn` pointing here — never an extra path on this one.

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
   e.g. `test/src/foo.ts` when `gitRoot` is `test`).
   **A file the task must CREATE belongs in `files` too, before it exists.** `files` is what the plan
   gate matches an edit against, and the gate asks the manifest, never the disk — so a declared path
   that is not there yet is a legitimate creation target and `/audit:task add` reports it as
   `note: not on disk (a new file?)` rather than as a problem. Leave it out and the executor is
   refused on its **first** write with no legal way forward: a live run wrote a task whose
   description ordered three new files while `files` named only the three it read, and the run
   dead-ended there. Say what the task will create, not only what it will read. When `gitRoot` is not `.`, prefer writing the
   manifest INSIDE the git root (set `manifestPath` accordingly, e.g. `test/docs/audit/audit-plan.json`,
   and mirror `gitRoot` into `.claude/audit.config.json`) so the orchestrator can commit its status
   history; note this to the user.

## 6. Present & approve (the gate)

Nothing synthesized has touched disk yet. Print the proposed plan, plain ASCII:

```
Proposed plan — 4 phases, 23 tasks

  id  title                 goal (desiredOutcome)         gate                    tasks
  P0  Build & test health   CI green; gate runnable        pnpm test --run         5
                                                          tsc --noEmit
  P1  Security hardening    no injection paths left        pytest -q               7
                                                          ! deploy.yml: no gate
  ...
  deferred: 3 item(s) (reasons below) - open questions: 2
```

"Key tasks" = the 2–3 highest-risk task titles per phase.

### 6.1 Skill suggestions (per task)

Before the gate, propose a `skills` list for every synthesized task — only when this
repo has anything to offer; a repo with no registered areas and an empty discovery
inventory skips this sub-step entirely and never mentions skills.

**Do not scan the filesystem for skills yourself — there is ONE mechanical source.**
Write the assembled candidate manifest (step 5.4) to a TEMP file (`mktemp` — never
`manifestPath`; the gate below still decides what lands on disk), run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <tmpfile> --json --discovery
```

and delete the temp file. The payload's `discovery` block is the inventory:
`{"skills": [{"name", "description", "source"}, …], "agents": […]}` — every skill
and agent this project can actually see (project `.claude/`, user `~/.claude/`,
installed plugins). A `discovery.error` key means the scan failed and the lists are
empty (fail-open, not wrong): say so and skip inventory suggestions rather than
guessing. Suggest from that output:

- **Area default first** — when the task's phase carries an `area` tag registered in
  `meta.areas` with `skills` (match `task.files` against the registered area `root`
  prefixes — roots and default skills come from the candidate's own `meta.areas`,
  which you assembled in step 3.5; the payload's `areas` block carries the per-tag
  rollup and advisory `owner`, not the roots), those are the baseline: they load
  first for every task in the area anyway, so do not repeat them on the task —
  suggest only ADDITIONS.
- **Inventory match** — suggest a `discovery.skills` name when its `name` or
  `description` matches the task's `files` (language, framework, path under an area
  root) or its subject (a security finding → a security-review skill). Offer names
  the payload carries and NOTHING else — never invent one.

Show every suggestion in the printed plan, one compact line per task that has any:

```
    P1.2  parameterize SQL in orders    skills: web-security (+ area default: backend-conventions)
```

When any suggestions exist, ask ONE AskUserQuestion (multi-select, all suggestions
pre-selected): **"Keep these per-task skill suggestions?"** — deselecting one drops
it from that task. Approved suggestions land in the materialized tasks as
`skills: [...]` (and travel inside parked payloads, so materialization preserves
them).

**The three-states rule — apply it as written, do not improvise:** a task with
nothing suggested or nothing approved is written with `skills: []` —
"unconsidered", the area default stays in force. Write `skills: null` ONLY when
the human explicitly says no skills apply to that task — null is the conscious
opt-out that STOPS the area fallback, and an init that invents opt-outs silently
turns the area defaults off.

### Phase priority (optional, and only when the interview said so)

When the interview made it plain that something has to go **first** — a security
finding they came here for, a release they are blocked on — set `priority` on that
phase: a positive integer, tier 1 for the one thing that leads. Leave every other
phase without the field; absent means unprioritised, and a plan where everything is
pinned has said nothing.

Say what you assigned, in the approval step, one line per pinned phase:

```
    P3  fix the SQL injection path              priority 1  (from: "this is why we called you")
```

**Only tier 1 is unique**, so never assign it twice; higher tiers are shared and are
for "roughly after that". And priority re-sorts work that is **already ready** — it
never makes an unready task ready and never skips a dependency. If a phase you would
pin depends on unfinished work, say that out loud instead of pinning it or rewriting
its `blockedBy`: a pin that its own dependencies contradict is a contradiction to
REPORT, not to repair.

Then ask ONE AskUserQuestion:

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

### 6.2 Layout — one file, or one file per phase

Ask once (AskUserQuestion), **after** the plan is approved, because the plan's size is half the
criterion and until now there was no size. Phrase it by what actually decides it, never by a
version number:

- **One file (default)** — one session at a time, a handful of phases. One file, one diff, no index
  to keep in step. This is what every manifest before this question was, so accepting the default
  changes nothing for anyone.
- **One file per phase (sharded)** — you will run phases **in parallel from separate git
  worktrees**, or the plan is big enough that loading every phase in order to run one costs real
  context. An index (`meta` · `bugs` · `fileIndex`) plus `phases/<phaseId>.json`.

Put the approved plan's phase count in the question, so the second criterion is answerable rather
than hypothetical. And say that **neither shape goes out of date and the choice is not final** —
`/audit:layout <sharded|single-file>` moves an existing manifest either way — so the question does
not read as a commitment it is not.

**Skip it entirely when nothing was materialized.** Everything parked as proposals means `phases[]`
is empty, and a layout for zero phases is a choice about nothing: write the single file and leave
the question for `/audit:layout` once a phase exists. Skipping is not defaulting quietly — say
which layout was written and why the question was not worth asking yet.

## 7. Write + validate

1. `mkdir -p` the manifest's parent directory; Write the manifest as decided in
   step 6 (approved phases in `phases[]` with their `fileIndex` entries; parked
   phases in `proposals[]`).
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` —
   on findings, fix and re-run until clean (this is mandatory).
3. If `npx` is available, also run
   `npx ajv-cli validate --spec=draft2020 -s "${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json" -d <manifestPath>`;
   if npx is missing, skip silently.
4. **If step 6.2 chose sharded, split it now** — never hand-write shards:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/migrate-manifest.py" <manifestPath> --to=sharded
   ```
   One splitter, one implementation: it validates the source, backs it up, writes the index and
   shards atomically, then re-validates the result and restores the backup on any failure. If it
   refuses, the single file you just wrote is what stays on disk — report the refusal and the
   layout the user actually has, never the layout they asked for.

## 8. Report

**Materialized (fully or partly):** per-phase table (`id — title — task count —
dimensions covered`), total task count by `tests.mode` and `risk`, what was
deferred and why, any open questions for the human, and the handoff: **next run
`/audit:status`, then `/audit:phase P0`**. Name every task whose `tests.gate` could NOT be
narrowed, with the reason its `description` records — a wide gate nobody was told about is
how a default teaches the wrong lesson, and this is the last place to say it before the plan
starts running. Name the layout that was written, and
when it is sharded, that the index and every `phases/*.json` are new files to
`git add` — plus that the `.bak-<UTC>` the split left behind is a copy of the file
written moments earlier, so on a fresh init it is noise and safe to delete.

**Parked (any):** a proposal table (`PROP-id — reserved phase — title — tasks`)
and the handoff: `/audit:propose list`, then
`/audit:propose materialize <id>|--all`. Add one note when everything was
parked: *the plan gate stays in its advisory (warn) tier until a phase is
materialized and running — same as any idle manifest; with `planGate: "deny"`
(or legacy `enforce: true`) an
empty-phases manifest denies out-of-plan edits (its fileIndex is empty), so
materialize a phase before starting fix work.*

When areas were registered, list them (`tag — root — reviewer`) and say which phases carry which
tag; `/audit:doctor` will warn about any root that is not a directory.
Release the concurrency lock if you acquired one in step 1.
