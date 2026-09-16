# Token-efficiency audit — the `audit` plugin

A read-only investigation of every path by which this plugin causes a user's Claude Code session to
spend tokens, and what can be done about each. Nothing in the repository was changed to produce it.

## 0. How to read this

**Evidence classes.** Every figure and every external claim carries one of these labels.

| Label | Means |
|---|---|
| `[measured-here]` | Produced by running a read-only command against this working tree during this audit. The command is in the row. |
| `[measured-run]` | Taken from the token measurements handed to this audit, read out of this project's own Claude Code transcripts during the current release run. Re-derivable with the scripts named in the benchmark plan. |
| `[official]` | Documented behaviour, with the URL. |
| `[community]` | Reported by somebody outside Anthropic, with the URL. Treated as a hypothesis, never as a basis. |
| `[inference]` | My reasoning from the two above. Not evidence. |

**Byte counts are measured; token counts are estimates.** No tokenizer is installed on this machine
and the token-counting endpoint was not called, so wherever a token figure appears it is bytes
divided by four and is labelled `ESTIMATE`. Byte counts are what the commands print. Where a
decision turns on a token count rather than a ratio, the benchmark plan in section 7 says how to get
the real number instead of estimating it.

**This document follows the repository's own rule about numbers.** Figures live in tables beside the
command that re-derives them, so a figure that rots is a figure a reader can catch.

---

## 1. Executive summary

The five highest-impact opportunities, in the order I would take them.

| # | Opportunity | Expected impact | Confidence | Reduces |
|---|---|---|---|---|
| E1 | Split `reference/orchestrator.md` so each command reads only the sections it executes | **High** | **High** — the saving is a byte count, not a behavioural guess | User tokens |
| E2 | Project the discovery payload and stop re-emitting large read-only renders as model output | **High** | **High** — both costs are measured below | User tokens (output tokens, the dearest kind) |
| E3 | Take command descriptions the model never needs out of every session's startup context | Medium | **High** — the mechanism is documented and the byte count is measured | User tokens, every session, including sessions that never touch the plugin |
| E4 | Bound and narrow each spawned agent: `omitClaudeMd` where the brief is self-sufficient, `maxTurns`, continue-don't-respawn, and *measure* `experimental.cacheTtl` instead of assuming it | **High** | Medium — the direction is supported by two independent measurements, the magnitude is not yet measured here | User tokens and latency |
| E5 | Make the per-task reviewer call configurable, and off in a low-token profile | Medium | **High** for the saving, Medium for the quality cost | User tokens and latency |

Two framings worth stating before the detail.

**The plugin's expensive surfaces are its instructions, not its code.** The Python is large and
costs the user nothing: it runs locally, and the two biggest artifacts it produces — the report page
and the panel page — never enter a context window at all. What costs tokens is prose the model is
told to read, and prose the model is told to re-type.

**The plugin already does the hardest part right.** `run-test-gate.py` collapses a whole test
runner's output into a bounded verdict before the model sees it — which is exactly the technique the
official cost guidance recommends as "offload processing to hooks and skills"
([official](https://code.claude.com/docs/en/costs#offload-processing-to-hooks-and-skills)). The
recommendations below extend a discipline that is already in the tree; none of them asks for a new
idea.

---

## 2. Current token-cost map

### 2.1 The three cost classes

| Class | What is in it | Who pays |
|---|---|---|
| **Deterministic local** | Every `.py` under `scripts/` and `hooks/`, the assembled panel page, the rendered HTML/Markdown report, the usage ledger, the journal, the evidence rows, the schemas | CPU and wall clock on the user's machine. **No model tokens.** |
| **Model input** | Command bodies, `reference/*.md`, agent system prompts, manifest reads, tool results (script stdout, file reads, diffs), CLAUDE.md in every non-fork subagent | Billed as input, or at the cache-read rate when the prefix survives |
| **Model output** | The model's own replies, its thinking tokens, and every render it is instructed to re-type verbatim | Billed at the output rate |

Output is the dearest class. Current list prices
([official](https://platform.claude.com/docs/en/about-claude/pricing), via the bundled `claude-api`
skill's cached table, 2026-06-24):

| Model | Input $/MTok | Output $/MTok | Cache read | 5m cache write | 1h cache write |
|---|---|---|---|---|---|
| Claude Opus 5 | 5.00 | 25.00 | ≈0.1× input | ≈1.25× input | ≈2× input |
| Claude Sonnet 5 | 2.00 | 10.00 | ≈0.1× input | ≈1.25× input | ≈2× input |
| Claude Haiku 4.5 | 1.00 | 5.00 | ≈0.1× input | ≈1.25× input | ≈2× input |

Cache multipliers are [official](https://code.claude.com/docs/en/prompt-caching#cache-lifetime) and
match the plugin's own bundled `usage.pricing` table. One consequence drives several
recommendations below: **a render the model re-types costs roughly five times what the tool result
that produced it cost, and roughly fifty times what reading it from cache would have cost.**

> **Data-accuracy note, not a token issue.** The plugin's bundled `usage.pricing` entry for
> `claude-sonnet-5` and the `claude-api` skill's cached table disagree. That affects what
> `/audit:usage` *reports*, not what a run *spends*. Settle it against the live pricing page before
> the next release.

### 2.2 What is loaded, and when

| Surface | Loaded | Mechanism |
|---|---|---|
| Command + agent + skill **descriptions** | **Every session start**, whether or not the plugin is used | "Every skill in the skill listing adds to your context on every turn, whether or not Claude ever uses it" ([official](https://code.claude.com/docs/en/skills)) |
| A command **body** | When that command is invoked | "full skill content only loads when invoked" ([official](https://code.claude.com/docs/en/skills)) |
| `reference/orchestrator.md`, `reference/manifest-conventions.md` | When an execution command is invoked — the command body's first instruction is to read them | `plugins/audit/README.md` calls `orchestrator.md` "the pipeline's execution core, read by the model on every `/audit:*` call" |
| An agent's **system prompt** | When that agent is spawned | [official](https://code.claude.com/docs/en/sub-agents) |
| The user's **CLAUDE.md hierarchy** | In **every** non-fork subagent spawn | "every level of the CLAUDE.md hierarchy the main conversation loads" ([official](https://code.claude.com/docs/en/sub-agents)) |
| `hooks.json` and the hook scripts | Session start / per matching tool call | Plugin hooks load automatically when the plugin is enabled ([official](https://code.claude.com/docs/en/plugins-reference)) |
| Panel page, report page, schemas, tests | **Never**, unless a human asks the model to read one | — |

The plugin ships **no MCP server** (`.mcp.json` absent), which matters: "Claude Code never
invalidates the cache for a plugin's skills, commands, agents, hooks, monitors, or themes"
([official](https://code.claude.com/docs/en/prompt-caching#plugin-components-that-keep-the-cache)).
Enabling and disabling this plugin is cache-safe. That is a real design win and should stay true.

### 2.3 Startup cost — paid by every session in every repository where the plugin is enabled

`[measured-here]` — description text only; bodies are excluded because they do not load at startup.

| Surface | Bytes of `description:` | Command that re-derives it |
|---|---|---|
| `commands/` (all) | 6,404 | see §7.1 script `startup-bytes` |
| `agents/` (all) | 1,515 | same |
| `skills/` (both) | 655 | same |
| **Total** | **8,574** (≈2,100 tokens, ESTIMATE) | same |

For scale: the official context-window walkthrough's illustrative session budgets a few hundred
tokens for the *whole* skill listing
([official](https://code.claude.com/docs/en/context-window)). A community measurement tool reports
per-skill listing costs spanning an order of magnitude and finds the skill catalogue to be the
dominant startup term ([community](https://github.com/iops-leo/claude-slim)). Either way this
plugin's contribution is not negligible, and it is paid in repositories that will never run an
audit.

### 2.4 Invocation cost — command bodies

`[measured-here]` — body bytes, frontmatter excluded. Only the invoked command's body loads.

| Command | Body bytes | | Command | Body bytes |
|---|---:|---|---|---:|
| `sync` | 66,327 | | `logs` | 5,767 |
| `task` | 43,404 | | `propose` | 5,762 |
| `init` | 39,544 | | `usage` | 4,836 |
| `phase` | 26,487 | | `worktree` | 4,582 |
| `status` | 19,283 | | `run` | 4,235 |
| `panel` | 15,976 | | `review` | 3,117 |
| `doctor` | 11,603 | | `resume` | 2,558 |
| `report` | 10,835 | | `next` | 1,964 |
| `layout` | 8,709 | | `migrate` | 1,556 |
| `bug` | 5,887 | | `guide` | 1,046 |

Re-derive with the `command-bodies` script in §7.1.

### 2.5 Invocation cost — the shared reference read

`[measured-here]` — `wc -c plugins/audit/reference/*.md`

| File | Bytes |
|---|---:|
| `reference/orchestrator.md` | 101,263 |
| `reference/manifest-conventions.md` | 24,379 |
| `reference/tracker-sync.md` | 19,250 |

The bodies of `next`, `run`, `phase`, `review`, `resume`, `report`, `worktree` and `layout` all open
with an instruction to read the first two. So a bare `/audit:next` on any plan loads its own body
plus both reference files before it has looked at the manifest. `status`, `doctor` and `usage` are
the exceptions — `status` reads `orchestrator.md` only when the operator asks a follow-up, which is
the pattern the rest of this section proposes generalising.

`orchestrator.md` broken down by section — `[measured-here]`, script `orchestrator-sections` in
§7.1. The percentages are of the part of the file from its first `## ` heading onward.

| Section | Lines | Bytes | Share |
|---|---:|---:|---:|
| Execute the task | 468 | 38,117 | 37.9% |
| Phase sign-off | 309 | 24,751 | 24.6% |
| Preflight | 90 | 7,597 | 7.6% |
| Concurrency lock | 67 | 4,554 | 4.5% |
| Readiness rule | 56 | 3,712 | 3.7% |
| Non-negotiable guardrails | 42 | 3,672 | 3.7% |
| At a glance | 46 | 3,524 | 3.5% |
| ADO echo | 46 | 2,897 | 2.9% |
| Progress output | 32 | 2,174 | 2.2% |
| Keeping a failed run's record | 33 | 2,017 | 2.0% |
| Reporting | 29 | 1,940 | 1.9% |
| Branch-per-phase | 30 | 1,757 | 1.7% |
| Answering one question about the trail | 24 | 1,269 | 1.3% |
| Resume after interruption | 15 | 1,115 | 1.1% |
| Dry-run / preview | 16 | 1,078 | 1.1% |

Which commands actually execute which sections `[measured-here]` from the command bodies:

| Command | Needs *Execute the task* | Needs *Phase sign-off* |
|---|---|---|
| `report`, `worktree`, `layout` | no | no |
| `status` | no | no (and it already reads the file only on request) |
| `run`, `next` | yes | no |
| `phase`, `review`, `resume` | yes | yes |

`/audit:report` is instructed to read the whole file and then told to run only preflight steps 1–2.

### 2.6 Tool-result volume — what the plugin's own scripts put into context

`[measured-here]`, against this repository's own plan at `docs/audit/audit-plan.json` (a large,
long-lived, sharded plan) and against `examples/acme-store/audit-plan.json` (a small one).

| Invocation | Bytes of stdout | Where it is used |
|---|---:|---|
| `audit-status.py <plan> --json --discovery` | 219,738 | `/audit:init` §3.5, `/audit:task add` |
| `audit-status.py <plan> --json --discovery --section discovery` | 74,054 | **nothing uses this today** |
| `audit-status.py <plan> --json` | 143,448 | `/audit:report`'s summary step |
| `audit-status.py <plan> --json --section usage` | 16,606 | orchestrator's budget check — the one caller that already projects |
| `audit-status.py <plan> --view all` | 38,842 | `/audit:status --view all` |
| `audit-status.py <plan>` (default view) | 18,180 | `/audit:status`, `/audit:next` step 0 |
| `audit-status.py <plan> --phase P40` | 1,671 | `/audit:phase` step 0 |
| `audit-usage.py <plan>` | 9,003 | `/audit:usage` |
| `audit-doctor.py` | 6,556 | `/audit:doctor` |
| `audit-status.py examples/acme-store/audit-plan.json` | 3,987 | the small-plan comparison |

Two of these are re-typed by the model on top of being read as a tool result. The command bodies say
so in as many words — `/audit:status`, `/audit:doctor`, `/audit:usage`, `/audit:logs`,
`/audit:propose` and step 0 of `/audit:next` and `/audit:phase` all instruct the model to print the
script's stdout verbatim in its own reply, inside a fenced block. The stated reason is sound and I
do not dispute it: a tool result is collapsed behind the tool call, and a live run ended with the
operator's report sitting one click away while the model believed it had answered. The cost is that
each of those renders is paid twice, and the second time at the output rate.

The scoped views are cheap. The whole-plan default view is not, and it grows for the life of a plan.
`commands/status.md` already anticipates this: "the render is printed verbatim, so its length is
paid on every call, and a plan's archive only ever grows." The folding of finished phases was the
first half of that fix. The second half is below.

### 2.7 Agent spawns

The pipeline's per-unit spawn pattern, read out of `reference/orchestrator.md`:

| Unit | Spawns | Agent | Frontmatter today |
|---|---|---|---|
| Per task | 1 | `audit-executor` | `effort: medium`, tools without `Agent` |
| Per task, when the gate came back green | 1 | `audit-reviewer` in `mode: task` | `effort: high` |
| Per phase sign-off, when a review skill resolves | 1 | `audit-reviewer` in `mode: phase` | `effort: high` |
| Per sign-off finding | 1 | `audit-executor` fix run | — |
| Per `/audit:init` | up to 6, in one message | `audit-explorer` | `effort: medium` |
| Per `/audit:guide` | 1 | `guide` | `model: haiku`, `effort: low` |

What a spawn costs, `[measured-run]` over the release run's subagents:

| Quantity | Value |
|---|---:|
| First-turn new cache per agent — median | 28,039 |
| First-turn new cache per agent — smallest / largest | 15,034 / 54,322 |
| Sum of all first turns as a share of the run's new cache | 4% |

So the spawn itself is not the problem, and "spawn fewer agents" is the wrong conclusion. What the
same measurement does say is that **lifetime is**:

| Agent lifetime | Agents | New cache per call |
|---|---:|---:|
| under 30 min | 51 | 3,325 |
| 30–90 min | 33 | 2,974 |
| 90–180 min | 4 | 3,425 |
| over 180 min | 19 | **8,560** |

Nineteen long-lived agents burned more new cache in fewer calls than fifty-one short ones. The
mechanism is that every later turn carries everything earlier and the cache is rewritten as its TTL
lapses, so cost is superlinear in lifetime and roughly flat in work done. Nothing in the product
bounds an agent's lifetime or its context.

The independent corroboration is worth reading in full: a community analysis of ~95 sessions and
~1,800 subagents reports that a subagent's cold start is overwhelmingly static content — system
prompt, tool schemas, project rules, environment — with only a few per cent unique task text, and
that most of it is re-written from scratch on each spawn rather than read from cache
([community](https://github.com/anthropics/claude-code/issues/74318)). The same analysis measures
that a **blanket one-hour TTL for subagents made things worse**, because the overwhelming majority
of subagent cache reuse happens within tens of seconds and the higher write rate is then paid for
nothing. That result is why recommendation R7 below asks for a measurement rather than a setting.

### 2.8 Hooks

`hooks.json` fires these per matching tool call:

| Tool | PreToolUse hooks | PostToolUse hooks |
|---|---:|---:|
| `Edit` / `Write` / `MultiEdit` / `NotebookEdit` | 3 | 4 |
| `Bash` | 3 | 2 |
| `mcp__*` | 5 | 2 |
| `Read` / `Grep` | 1 | 0 |
| `Skill` / `Task` / `Agent` | 1 | 0 |
| every user prompt | 1 (`UserPromptSubmit`) | — |
| every `Stop` / `SubagentStop` / `SessionEnd` | 1 | — |

Latency, `[measured-here]` with `python3 tools/bench-hooks.py` on this machine:

| Lane | Slowest hook | ms |
|---|---|---:|
| baseline | bare interpreter start | 14.34 |
| edit | `require-plan.py` | 34.47 |
| bash | `guard-bash-writes.py` | 37.46 |
| read | `guard-secrets-read.py` | 26.93 |

"All matching hooks run in parallel"
([official](https://code.claude.com/docs/en/hooks)), so the added latency per tool call is the
slowest hook rather than the sum. That figure is small.

**The hooks cost almost no tokens, and that is by design.** For every event this plugin uses except
`UserPromptSubmit`, exit-0 stdout goes to the debug log and Claude never sees it; only
`additionalContext` reaches the model ([official](https://code.claude.com/docs/en/hooks)). The one
context-injecting hook is `remind-tdd.py`, and it is throttled to once per file per session with a
minimum gap and a short fixed template. `meter-usage.py` and `detect-plan-skip.py` speak only
through `systemMessage`, which is user-visible and not in context.

**Where hooks do cost tokens is a refusal.** A `PreToolUse` deny or ask reaches the model, and the
model then spends a turn reading it and a turn retrying. This audit hit two such refusals on
read-only analysis commands whose writes were outside the repository. Both came from the **installed
copy of the plugin, which this session is pinned to** — `.claude/state/running-plugin-<session>.json`
records `2.0.1`, while the working tree is at `2.3.0`. Driving the working tree's own decision
function over the same command text returns `allow` with the honest basis *"write destination not
established … the shell resolves it and the payload does not carry the result, so the plan cannot be
asked about it"*. So the specific defect is already fixed; the **class** is live, and section 3
treats it as one:

- a guard false positive costs a model turn to read plus a turn to retry, every time;
- the copy of the plugin that guards a session is fixed when the session starts, so a user keeps
  paying for a defect for as long as their session lives — which is precisely why the
  `running-plugin` stamp and `/audit:doctor`'s reading of it exist.

### 2.9 Where a user's tokens actually go, ranked

`[inference]` from §2.3–§2.8, to be confirmed by the benchmark in §7.

1. **Subagent context that is re-paid on every spawn and every cache lapse** — the executor and
   reviewer briefs plus the user's whole CLAUDE.md hierarchy, multiplied by tasks, retries and
   sign-off fix runs.
2. **`reference/orchestrator.md` read whole on every execution command**, with the two largest
   sections unused by several of the commands that read them.
3. **Unprojected script payloads** — the discovery payload above all.
4. **Verbatim re-emission of large renders as output tokens.**
5. **Startup description text** in every session, including sessions that never invoke the plugin.
6. **Retries** — each one re-pays from zero; a fan-out that died on a rate limit and was re-driven
   as fresh agents is what made six hours cost more than the preceding full day in the release run
   (`[measured-run]`).

---

## 3. Recommendation backlog

Each item names the components, the change, why it saves, what it costs, whether it is reversible,
and its priority.

---

### R1 — Split `reference/orchestrator.md` into sections and read only what the command runs

**Priority P0. Reversible: yes (pure content reorganisation).**

**Components.** `reference/orchestrator.md`; every command body that opens with "Read
`reference/orchestrator.md` … first" — `next`, `run`, `phase`, `review`, `resume`, `report`,
`worktree`, `layout`; `plugins/audit/README.md`'s cross-reference table;
`scripts/_refs.py` (the drift lints that read this file by name);
`scripts/governance/_invariants.py`.

**Current behaviour.** One file, read whole, on every execution command. Section 2.5 shows *Execute
the task* and *Phase sign-off* together are the clear majority of it, and shows which commands run
neither.

**Proposed behaviour.** Keep `orchestrator.md` as a **map plus the always-needed core** — *At a
glance*, *Preflight*, *Non-negotiable guardrails*, *Readiness rule*, *Concurrency lock*,
*Branch-per-phase*, *Progress output*, *Dry-run / preview*, *Reporting* — and move the two large
procedures to `reference/orchestrator/execute-task.md` and `reference/orchestrator/phase-signoff.md`,
with *ADO echo* going to `reference/orchestrator/ado-echo.md`. Each command body then names the
files it needs:

- `report`, `worktree`, `layout`, `status` → the core only;
- `run`, `next` → core + `execute-task.md`;
- `phase`, `review`, `resume` → core + `execute-task.md` + `phase-signoff.md`.

This is precisely the progressive-disclosure pattern the skills documentation prescribes: "Keep
`SKILL.md` under 500 lines. Move detailed reference material to separate files … you pay the cost
only when Claude navigates to those files"
([official](https://code.claude.com/docs/en/skills)).

**Why it reduces tokens.** The saving is a byte count taken straight from §2.5, not a behavioural
guess. It applies on every execution command, on every plan, for every user.

**Tradeoff.** Two costs, both real. First, a procedure split across files can drift, and this
repository's whole culture is against two copies of one procedure — so the split must be a **cut,
not a copy**, with no section restated in two places, and `_refs.py`'s existing drift lints must be
pointed at the new paths so a section that goes missing fails the build by name. Second, a reader
following a cross-reference now opens a second file; the map section has to be good enough that
nobody guesses.

**Complexity.** Low mechanically, medium in review: the lints and `README.md`'s invariant table both
address `orchestrator.md` by name.

**Quality/safety impact.** Preserved if the cut is clean. There is one genuine risk to name: the
*Non-negotiable guardrails* section must stay in the always-read core, because a command that skips
it is a command running without the invariants.

---

### R2 — Project the discovery payload

**Priority P0. Reversible: yes (one flag in two command bodies).**

**Components.** `commands/init.md` §3.5, `commands/task.md`'s skills step,
`scripts/status/audit-status.py`.

**Current behaviour.** Both call `audit-status.py … --json --discovery` and use only
`discovery.skills`. The whole rollup — phases, tasks, bugs, usage, findings, warnings — comes back
with it. Section 2.6 has both figures.

**Proposed behaviour.** Add `--section discovery` to both call sites. The projection already exists
and already works; the orchestrator's budget check uses it for `usage` and explains exactly why:
"This step needs one array and used to read the entire payload to reach it, which on a long-lived
plan is tens of kilobytes of context spent per phase start."

Then go one step further in the script: in discovery mode, cap each entry's `description` at a
length that still lets a model choose a skill by name. The entries are already truncated; they are
still the bulk of the payload.

**Why it reduces tokens.** Measured in §2.6, on this repository's own plan, with the plugin's own
command. `/audit:task add` runs this against the real manifest, so it pays the full amount every
time somebody adds a task.

**Tradeoff.** `discovery` does not appear in the section list `--section` prints on a bad key,
because that list is computed on a payload built without `--discovery`. Fix that too, or the flag is
undiscoverable. Capping descriptions trades a little of the model's ability to pick the right skill;
measure it before shipping the cap, and ship the `--section` half unconditionally.

**Complexity.** Trivial for the flag. Low for the cap.

**Quality/safety impact.** None for the flag — a projection is the same payload's key, so nothing
can disagree with what `--json` says. The cap is a judgement call about how much description a model
needs to choose.

---

### R3 — Stop re-typing the large renders; keep re-typing the small ones

**Priority P0. Reversible: yes.**

**Components.** `commands/status.md`, `commands/next.md` step 0, `commands/doctor.md`,
`commands/usage.md`, `commands/logs.md`, `commands/propose.md`;
`scripts/status/audit-status.py`.

**Current behaviour.** Each of those bodies instructs the model to print the script's stdout
verbatim in its own reply. Section 2.6 gives the sizes; §2.1 gives the price ratio.

**Proposed behaviour.** Keep the instruction for renders that are small — `/audit:phase`'s scoped
entry view and `/audit:doctor` are already in that class. For the whole-plan views, give
`audit-status.py` a `--brief` human render: the overall line, the usage line, the READY NOW block
with its copy-pasteable `/audit:run <id>`, the open-bug count, and a final line naming the command
that prints the rest. Change `/audit:next` step 0 to echo `--brief`, and have `/audit:status` echo
`--brief` by default while passing an explicit `--view`/`--phase` straight through unchanged.

**Why it reduces tokens.** It removes the duplicate, and the duplicate is the expensive copy. The
information the operator needs in order to act — what is ready and what to type — is a small part of
the render.

**Tradeoff.** This is a real reduction in what the operator sees without asking. The reason the
verbatim instruction exists is a live run that ended with the report collapsed behind a tool call
and the model believing it had answered; `--brief` must not recreate that. The mitigation is that
`--brief` ends by naming the command for the full view, so the fuller answer is one line away rather
than invisible. **I would not ship this without asking the operator**, because it trades their
default visibility for tokens and they are the one who knows which they want. It is the one
recommendation here where the cheaper option is not obviously the better one.

**Complexity.** Low.

**Quality/safety impact.** No assurance changes — `--gate`, `--json` and the evidence trail are
untouched. UX cost as described.

---

### R4 — Take descriptions the model never needs out of startup context

**Priority P1. Reversible: yes (one frontmatter line per command).**

**Components.** `commands/sync.md`, `layout.md`, `migrate.md`, `logs.md`, `worktree.md`,
`panel.md`, `propose.md`, `bug.md`.

**Current behaviour.** Every command's description is in every session's context. §2.3 has the
total.

**Proposed behaviour.** Set `disable-model-invocation: true` on the commands a human always types
and the orchestrator never calls. The documented effect is exactly this
([official](https://code.claude.com/docs/en/skills)):

| Frontmatter | You can invoke | Claude can invoke | When loaded into context |
|---|---|---|---|
| (default) | Yes | Yes | Description always in context, full skill loads when invoked |
| `disable-model-invocation: true` | Yes | No | **Description not in context**, full skill loads when you invoke |

The docs also recommend the field for exactly this shape of command: "Use this for workflows with
side effects or that you want to control timing, like `/commit`, `/deploy`". `/audit:sync push`
writes to a remote tracker; `/audit:layout` rewrites the manifest layout; `/audit:logs prune`
deletes rows. These are textbook cases on their own merits, before the token argument.

**What must stay model-invocable, and why.** Anything the pipeline itself invokes by name. The
orchestrator's sign-off procedure literally tells the model to run `/audit:task add …` and then
`/audit:run <id>`, so `task` and `run` must stay. The two auto-triggering skills
(`audit-codebase`, `audit-spend`) are the discovery path — they exist so that "audit this codebase"
finds the plugin without a command name — so their descriptions stay, and whatever they route to
stays reachable. Before shipping this, grep the command bodies, the agent briefs and the reference
files for every `/audit:` mention and make the invocable set the closure of that, not a guess.

**Why it reduces tokens.** It is paid in every session in every repository where the plugin is
enabled, including sessions that never open the plan. That is the only cost in this document with
no opt-out today.

**Tradeoff.** A user who says "sync my audit to the board" instead of typing `/audit:sync` no longer
gets routed automatically. That is a genuine discoverability loss; the mitigation is a line in the
`audit-codebase` skill naming the typed commands.

**Complexity.** Trivial.

**Quality/safety impact.** Improved, slightly: a model can no longer decide on its own to push to a
tracker or rewrite a manifest layout.

---

### R5 — `omitClaudeMd` where the brief is self-sufficient

**Priority P1. Reversible: yes.**

**Components.** `agents/guide.md`, `agents/audit-explorer.md`, `agents/audit-reviewer.md`.

**Current behaviour.** Every non-fork subagent loads the user's whole CLAUDE.md hierarchy
([official](https://code.claude.com/docs/en/sub-agents)). None of the four agents opts out.
`omitClaudeMd: true` launches without user, project and local CLAUDE.md while managed policy files
still load, and is documented for "subagents that take everything from delegation prompt" (requires
Claude Code v2.1.271+).

**Proposed behaviour.**

| Agent | Recommendation | Reason |
|---|---|---|
| `guide` | `omitClaudeMd: true` | It answers questions about the plugin from the plugin's own docs with a citation for every claim. The consuming project's conventions are noise for that job. |
| `audit-explorer` | Make it a manifest/config choice, default *keep* | Project conventions can be the difference between a finding and a false positive. The explorer fans out up to six ways, so this is where the multiplier is — but it is also where a wrong call costs plan quality. |
| `audit-reviewer` (`mode: task`) | Make it a config choice, default *keep* | Its brief already lists every input it is handed and tells it to report a missing input rather than assume one; that discipline is what would make the opt-out safe. Still a judgement about review quality, so measure it. |
| `audit-executor` | **keep CLAUDE.md** | It writes code in the user's repository. This is the one place the hierarchy is load-bearing. |

**Why it reduces tokens.** It removes a fixed block from each spawn's cold start, and cold start is
overwhelmingly static content re-written per spawn
([community](https://github.com/anthropics/claude-code/issues/74318)). The size of the block is the
user's, not the plugin's — which is why the plugin should also *say* so: `/audit:doctor` is the
natural place to report the size of the CLAUDE.md hierarchy every spawn will carry, against the
official guidance to "keep CLAUDE.md under 200 lines by including only essentials"
([official](https://code.claude.com/docs/en/costs#move-instructions-from-claude-md-to-skills)).

**Tradeoff.** Named per agent above. The honest summary: for `guide` there is no tradeoff; for the
other two there is one and it is about output quality, not safety.

**Complexity.** Trivial for the frontmatter; low for the config key and the doctor line.

**Quality/safety impact.** Unchanged for `guide`. For the others, measure before changing the
default — see §7.

---

### R6 — Bound the agent, and continue it instead of respawning it

**Priority P1. Reversible: yes.**

**Components.** `agents/audit-executor.md`, `agents/audit-reviewer.md`,
`reference/orchestrator.md` → *Execute the task*.

**Current behaviour.** Nothing bounds an executor's turn count or its context. The orchestrator
already gets the most important half right and says why: a widened scope **continues** the running
executor rather than respawning it, because a re-spawn throws away everything it has read — measured
on a live run at five refusals resolved by re-spawning, about a third of that phase's whole cost.

**Proposed behaviour.** Three additions.

1. Set `maxTurns` on `audit-executor` and `audit-reviewer`. Partial output is marked as such and
   Claude can resume to continue ([official](https://code.claude.com/docs/en/sub-agents)), so a
   bound is not a truncation — it is a checkpoint. It converts the open-ended, superlinear cost of a
   long-lived agent (§2.7) into a decision the orchestrator makes with the plan in front of it. Pick
   the number from the benchmark, not from taste.
2. Extend the continue-don't-respawn rule to the **retry** arm. Today a retry increments `attempts`
   and the orchestrator is told to re-brief a fresh executor with what the last attempt proved. A
   `SendMessage` to the still-live executor carrying the same brief costs nothing of what it has
   already read. Where the agent is genuinely gone, the existing re-brief stands.
3. Spend the phase's `budgetUSD` at spawn time. The schema carries it, the preflight checks it
   against recorded spend, and nothing reserves against it before an executor is created — so a
   phase can pass the check and then spend the rest of the budget inside one agent.

**Why it reduces tokens.** `[measured-run]`: new cache per call for agents living over three hours
is roughly two and a half times that of agents living under thirty minutes (§2.7). A retry re-pays
from zero, and the plan already knows the attempt count.

**Tradeoff.** A `maxTurns` set too low turns one agent into two, and the second pays a cold start.
That is why the number comes from the benchmark. Continuing a retried executor means it keeps its
own prior reasoning, including whatever was wrong about it — which is sometimes exactly what you do
*not* want after a red gate. Make it the orchestrator's judgement with the rule stated, not an
unconditional instruction.

**Complexity.** Low for `maxTurns`; medium for the retry arm (it is a change to a procedure several
documents describe); medium for budget reservation.

**Quality/safety impact.** Improved on the runaway axis: a bounded agent is a bounded blast radius,
and the concurrency spike in the release run was an unbounded fan-out (`[measured-run]`).

---

### R7 — Measure `experimental.cacheTtl` before setting it

**Priority P1. Reversible: yes. Needs benchmark data before adoption.**

**Components.** `agents/audit-executor.md`, and documentation of the
`subagentPromptCacheTtl` setting for users.

**Current behaviour.** Subagents fall outside the main-conversation TTL bucket and get five minutes
even on a subscription, until you choose a longer one
([official](https://code.claude.com/docs/en/prompt-caching#which-ttl-each-request-gets)). The
audit executor's turns are separated by whole test-suite runs, so a suite that takes longer than the
TTL means the next turn re-reads the agent's entire prefix.

**The obvious fix is measured to backfire.** A community analysis of ~1,800 subagents reports that a
blanket one-hour subagent TTL made overall cost *worse*, because the overwhelming majority of
subagent cache reuse happens within tens of seconds and the higher write rate is then paid on every
write for nothing ([community](https://github.com/anthropics/claude-code/issues/74318)). So the
recommendation is **not** "set `cacheTtl: 1h`".

**Proposed behaviour.** Measure the executor's own inter-turn gap distribution — the benchmark in
§7.3 says how — and set `experimental.cacheTtl: 1h` on `audit-executor` only if its gaps actually
straddle five minutes, which they will exactly when the project's gates are slow. Whatever the
answer, document `subagentPromptCacheTtl` in the plugin's own README as a user-side knob, because
the user's gate runtime is the variable and only they know it.

**Tradeoff.** Named above: a one-hour write costs roughly 2× base input against roughly 1.25× for
five minutes, so one avoided full rebuild pays for it and none wasted does not.

**Complexity.** Trivial to set; the work is the measurement.

**Quality/safety impact.** None either way.

---

### R8 — Make the per-task reviewer call a configured choice

**Priority P1. Reversible: yes.**

**Components.** `reference/orchestrator.md` → *Execute the task*, the reviewer spawn step;
`agents/audit-reviewer.md`; `schema/audit-config.schema.json`; `commands/panel.md`'s composition
card.

**Current behaviour.** After every green task gate, the orchestrator spawns `audit-reviewer` in
`mode: task` with the diff, the task description verbatim, the phase's desired outcome, the
executor's claim, the evidence pointer and the gate commands. The brief runs at `effort: high`, and
thinking tokens are billed as output
([official](https://code.claude.com/docs/en/costs#adjust-extended-thinking)). The orchestrator is
explicit that this call blocks nothing: "the run's own recorded outcome is the verdict either way".

**Proposed behaviour.** A config key — `review.perTask` with values `always` (today's behaviour),
`risky` and `never`. `risky` runs the call only where the answer can change a decision: `task.risk`
of `med` or `high`, a `tdd` task whose `redFirst` did not come back `proved`, or a gate whose row
disagrees with the executor's return. Default `always`, so nothing changes for anyone who does not
opt in; the low-token profile in §5 sets `risky`.

**Why it reduces tokens.** It removes one high-effort spawn per task from the profile that asks for
it. §2.7's spawn table is the per-unit cost.

**Tradeoff — and this is the one that matters.** The intent question is the only place a claim can
be bound to the task that produced it: "the phase diff has no way back to the task that produced
each line, so a claim is bindable to its task only here". Setting `never` genuinely removes an
assurance — it is not a saving, it is a purchase. `risky` keeps the question where a wrong answer
costs something and drops it where the gate has already answered. State that in the config key's own
description so nobody chooses it without reading what they are giving up.

**Complexity.** Medium — a new config key, its validator entry, its panel control, and a rule the
orchestrator applies.

**Quality/safety impact.** Explicitly weakened at `never`, narrowed at `risky`, unchanged at
`always`. The evidence ledger, the gate, the commit scope and the journal are untouched at every
setting.

---

### R9 — Stagger the explorer fan-out so siblings can share a cached prefix

**Priority P2. Reversible: yes. Needs measurement.**

**Components.** `commands/init.md` §4.

**Current behaviour.** Up to six explorers are spawned in one message so they run in parallel. They
share everything except the task text: the same system prompt, the same tool set, the same CLAUDE.md,
the same environment.

**Proposed behaviour.** Consider spawning the first, then the rest a beat later. Claude Code already
does this for workflow fan-outs of same-prefix agents — it "holds all but the first for up to 5
seconds by default, so their first requests can read the prefix that the first agent cached"
([official](https://code.claude.com/docs/en/prompt-caching#subagents-and-the-cache)).

**Why it might reduce tokens.** `[inference]`: the same prefix-sharing logic applies to an
`Agent`-tool fan-out of one agent type. If it does, every explorer after the first turns a cold
start into a cache read.

**Tradeoff.** It adds wall clock to `/audit:init`, and I could not confirm that the documented
workflow behaviour extends to an `Agent`-tool fan-out. **Do not ship this on the inference.** The
benchmark in §7.4 settles it in one run.

**Complexity.** Trivial if it works.

**Quality/safety impact.** None.

---

### R10 — Treat a guard false positive as a token defect, not only a UX defect

**Priority P1. Reversible: n/a (a process and a gate, not a feature).**

**Components.** `hooks/guard-secrets-read.py`, `hooks/require-plan.py`, `hooks/guard-edits.py`,
`hooks/guard-bash-writes.py`; `tools/prove-gates.py`.

**Current behaviour.** The guards already draw the distinction that matters — the working tree's
decision function answers "write destination not established" rather than refusing, and says why.
That is the right shape. What is missing is that the cost of getting it wrong is not counted
anywhere.

**Proposed behaviour.** Two things. First, state the cost in `SECURITY.md`'s fail-open/fail-loud
table: a false refusal is not free, it is a model turn to read plus a turn to retry plus a push
toward a workaround. Second, extend `prove-gates.py`'s allow-case arm — which already exists to
catch a guard weakened until it over-fires — with the cases this class actually produces: a write to
a path built from a shell variable, a write to an absolute path outside the repository, and a
command whose payload merely *quotes* a write. The first two of those were the refusals this audit
hit under the installed copy.

**Why it reduces tokens.** Indirectly but reliably. It also protects the guard itself: the user's
own record of this class is that a guard which fires on a read gets routed around inside a day.

**Tradeoff.** More allow cases mean more surface a genuine evasion could be written to look like.
Every widening needs its red-first case in both directions, which is what `prove-gates.py` is for.

**Complexity.** Low.

**Quality/safety impact.** Improved. A guard nobody routes around is worth more than a guard that
catches one more shape.

---

### R11 — Report the plugin's own context cost in `/audit:doctor`

**Priority P2. Reversible: yes.**

**Components.** `scripts/status/_doctor_setup.py`, `commands/doctor.md`.

**Proposed behaviour.** A `context` section in the doctor's output: the byte total of the
descriptions this plugin puts in every session (§2.3), the size of the CLAUDE.md hierarchy each
spawn will carry, and the size of the manifest index a phase run reads. Point at `/skill-doctor`,
which "reports what each of your skills costs and how often it gets used" and requires Claude Code
v2.1.252+ ([official](https://code.claude.com/docs/en/skills)), and at `/context`.

**Why it reduces tokens.** It does not, directly. It makes the cost visible, which is the thing this
plugin is philosophically about: a claim carries the basis that makes it true. A plugin that meters
the user's model spend and cannot say what it costs them itself has a gap in its own doctrine.

**Complexity.** Low.

---

### R12 — Give the gate wrapper an explicit output budget

**Priority P2. Reversible: yes.**

**Components.** `scripts/governance/run-test-gate.py`.

**Current behaviour.** Already good: the wrapper prints one line per step plus a capped list of
failing lines with the basis for that cap, rather than the runner's raw stdout. The caps are
constants in the source.

**Proposed behaviour.** Surface them as a config key under `evidence` so a project with an
enormously chatty runner can tighten them, and a project debugging a flake can widen them for one
run. Keep the current values as defaults.

**Why it reduces tokens.** Small, but it is on the hot path — the gate runs per attempt, per task,
per phase.

**Tradeoff.** A tighter cap can hide the line that would have explained a red. The basis line the
wrapper already prints is what stops that being silent.

**Complexity.** Low.

---

## 4. Remove or radically simplify

Judged on whether the surface earns its cost — in startup context, in maintenance, and in the
reader's attention.

### 4.1 `/audit:migrate` — remove

It is the legacy spelling of `/audit:layout sharded` and says so in its own description. It carries
a body, a description in every session's context, and a row in every enumeration that lists
commands. `COMPATIBILITY.md` makes removing an accepted spelling a major release, so this is a
next-major item, not a patch — but it should be *on* that list rather than living forever. Until
then, `disable-model-invocation: true` (R4) takes its description out of startup context at no
compatibility cost, since a legacy spelling exists to be typed.

### 4.2 The Azure DevOps connector — split into a second plugin

`[measured-here]`:

| Surface | Bytes |
|---|---:|
| ADO scripts under `scripts/manifest/` + `scripts/status/_doctor_ado.py` | 712,711 |
| ADO tests under `tests/` | 418,507 |
| `commands/sync.md` body | 66,327 |
| `reference/tracker-sync.md` | 19,250 |

The marketplace manifest already takes a `plugins` array, so `audit` and `audit-ado` from one
repository is a supported shape ([official](https://code.claude.com/docs/en/plugins-reference)). The
token argument on its own is modest — a description in the listing and a command body that only
loads when invoked. The stronger arguments are the other two: `sync.md`'s `allowed-tools` names
`mcp__azure-devops__*` tools that most users will never have, and over a megabyte of tracker-specific
code and tests sits in the install for everyone.

**What it would cost.** `meta.ado` lives in the shared schema and the orchestrator's *ADO echo*
section is woven into *Execute the task* and *Phase sign-off*. A split means the core keeps the
schema block and the echo becomes a documented extension point that the second plugin fills. That is
a real design change, not a file move — which is why it is a proposal rather than a step in the
roadmap.

### 4.3 The per-task reviewer call — not removed, made a choice

Covered in R8. Removing it outright would be the wrong call: it is the only place a claim binds to
its task. Making it a setting with an honest description of what `never` gives up is the right one.

### 4.4 `/audit:worktree`, `/audit:logs`, `/audit:propose`, `/audit:layout` — keep, demote

All four are low-frequency, human-typed, and two of them mutate. They earn their place; they do not
earn a description in every session's context. R4 covers them.

### 4.5 The panel and the report — keep, unchanged

These are the plugin's cheapest surfaces per unit of value: the assembled panel page and the
rendered report never enter a context window. `/audit:report`'s optional AI summary is the only
model cost in either, and it is a few sentences. No change recommended, beyond R1 removing the
sections of `orchestrator.md` that `/audit:report` reads and cannot use.

### 4.6 What should *not* be simplified

Said plainly, because a token audit invites the opposite conclusion:

- **`run-test-gate.py`'s bracketing.** It is large because a gate is a measurement with five
  distinct failure modes, and collapsing them would put raw runner output back into context. It is
  the single best token decision in the tree.
- **The evidence ledger, the journal, the commit pathspec, the plan gate.** These cost the model
  almost nothing — they are local writes and local reads — and they are the assurance the plugin
  exists to provide.
- **The deterministic scripts generally.** Every verb that replaced a prose procedure with a script
  moved work off the model. That is the direction of travel, and it should continue.

---

## 5. Proposed install and runtime profiles

Three profiles. The mechanism is one config block plus which components are installed; the guarantees
column is what a user is actually buying.

| | **minimal** | **standard** (today's behaviour) | **strict governance** |
|---|---|---|---|
| **Installed** | `audit` core only | `audit` core | `audit` core + `audit-ado` (§4.2) |
| **Commands in startup context** | the routing skills plus `status`, `next`, `run`, `phase`, `report` | the same, plus `init`, `resume`, `review`, `doctor`, `task`, `usage`, `guide` | all |
| **Reference read per command** | core sections only; procedure sections on demand (R1) | same | same |
| **Hooks** | plan gate, secret guard, capability guard | all, as shipped | all, plus `journal.strictManifestState` |
| **Per-task reviewer** | `review.perTask: risky` | `always` | `always` |
| **Executor gate policy** | `executor.runsGate: never` — the orchestrator's recorded run is the only measurement | `own-tests` (today's default) | `full` |
| **TDD reminder** | off | on | on |
| **Token metering** | on — it is local and it is how you measure the rest | on | on |
| **Renders echoed verbatim** | `--brief` (R3) | full render | full render |
| **Guarantees retained** | The gate is still the signer, evidence rows are still recorded and committed, the plan gate still bounds every edit, commit scope is still explicit, the journal still chains | Everything above plus the per-task intent question and the executor's own quick check | Everything above plus full gate runs inside the executor loop and tracker echo |
| **Guarantees given up** | Per-task claim-to-task binding becomes conditional; the executor develops without running its own tests; no TDD nudge | — | — |

Two notes on the shape.

`executor.runsGate: never` deserves its name: the orchestrator's own recorded run is what becomes
evidence either way, so this setting removes a *development-time* check inside the agent, not the
measurement the plan is graded by. That is why it is the minimal profile's largest single saving and
also its most defensible.

A profile should be a **named preset that writes `.claude/audit.config.json`**, not a fork of the
plugin. `/audit:init` should offer the three, and `/audit:doctor` should print which one the config
resolves to — because the alternative is a profile that exists in a document and nowhere a command
can be asked about it.

---

## 6. Implementation roadmap

Each step is independently shippable, and each names what would catch it going wrong. The repository's
own gates (`tools/verify.sh`, `tools/prove-gates.py`) are the regression net; the additions below are
what those do not already cover.

### Step 1 — the free wins (one change set, no behaviour change)

| Change | Validation |
|---|---|
| R2: add `--section discovery` at both call sites; make `discovery` appear in the section list a bad key prints | The projection is the same payload's key; assert the projected `discovery` equals the full payload's `discovery` in a selftest case |
| R4: `disable-model-invocation: true` on the human-typed commands | A new lint: every `/audit:<name>` mentioned in a command body, an agent brief or a reference file must resolve to a command **without** that flag. This is the guard that stops the change breaking sign-off's `/audit:task add` |
| R5 (`guide` only): `omitClaudeMd: true` | Ask `/audit:guide` a question whose answer is in the plugin's docs and confirm the citation still comes back |

No benchmark needed. These change no procedure.

### Step 2 — the reference split (one change set, content only)

| Change | Validation |
|---|---|
| R1: cut `orchestrator.md` into a core plus `execute-task.md`, `phase-signoff.md`, `ado-echo.md`; update every command body's read instruction | `_refs.py`'s drift lints re-pointed at the new paths, so a section that goes missing fails by name. `README.md`'s invariant table updated in the same commit. A grep asserting no section heading appears in two files |

Regression risk is drift, not behaviour. The gate is that the cut copies nothing.

### Step 3 — the render decision (needs the operator's answer first)

| Change | Validation |
|---|---|
| R3: `--brief` render; `/audit:next` step 0 and `/audit:status` default to it | Selftest cases pinning that `--brief` carries the overall line, the READY NOW block with its `/audit:run` ids, and the pointer to the full view. **Ask the operator before changing the default** — this one trades their visibility |

### Step 4 — the agent envelope (needs benchmark data)

| Change | Validation |
|---|---|
| R6: `maxTurns` on executor and reviewer | §7.2 — the number comes from the measured turn distribution, not from taste |
| R6: continue a retried executor where it is still alive | §7.2 — compare total spend per completed task across the two shapes |
| R7: `experimental.cacheTtl` on the executor | §7.3 — **do not ship without it**; the naive version is measured to backfire |
| R9: stagger the explorer fan-out | §7.4 — **do not ship on the inference** |

### Step 5 — the configurable assurances

| Change | Validation |
|---|---|
| R8: `review.perTask` | Schema entry, validator case, panel control, and a `/audit:doctor` line naming the resolved value and its basis. §7.5 measures what `risky` misses |
| R5 (explorer, reviewer): config key for `omitClaudeMd`, default keep | §7.5 — plan quality is the metric, not tokens |
| Profiles (§5) as presets `/audit:init` offers and `/audit:doctor` reports | A doctor line naming the profile and what put it there |

### Step 6 — the structural proposals

R10 (`prove-gates.py` allow cases), R11 (doctor's context section), R12 (gate output budget), and
§4.2 (the ADO split, a major release). R10 and R11 are small and can go earlier if convenient; §4.2
needs a design decision that is not this document's to make.

---

## 7. Benchmark plan

**No saving in this document should be declared without a measurement.** The byte counts in §2 are
measurements of *inputs*; they are not measurements of *spend*. What follows is how to turn them into
one.

### 7.0 The instrument

The measurement already used to produce the `[measured-run]` figures is the right one and needs no
new infrastructure: every assistant entry in a Claude Code transcript carries a `message.usage`
block with `input_tokens`, `output_tokens`, `cache_read_input_tokens` and
`cache_creation_input_tokens`; the main session is one file and each subagent writes its own under
`<session-id>/subagents/agent-<id>.jsonl`. `spend.py`, `spend2.py` and this plugin's own
`scripts/usage/` readers all consume that shape, and `/audit:usage` already attributes it by phase,
task, model and author.

**Report `output + cache_creation` as the headline, not the raw total.** Cache reads are the
discounted term and including them at face value makes a long, well-cached session look like the
expensive one. Report cache reads separately.

**Convert estimates to real token counts where a decision turns on one.** `messages.count_tokens`
is the way to price a file — never a third-party tokenizer.

### 7.1 Re-deriving the static figures in this document

Three read-only scripts. None of them touches the repository.

| Name | What it prints | Feeds |
|---|---|---|
| `startup-bytes` | Sum of `description:` bytes across `commands/`, `agents/`, `skills/` | §2.3 |
| `command-bodies` | Body bytes per command, frontmatter excluded | §2.4 |
| `orchestrator-sections` | Lines and bytes per `## ` section of `reference/orchestrator.md` | §2.5 |

The tool-result figures in §2.6 are re-derived by piping each listed invocation through `wc -c`. The
hook latency figures come from `python3 tools/bench-hooks.py`.

### 7.2 The representative workflows

Four, each run on a fixed commit of a fixed target repository so the work is identical across arms.
`examples/acme-store/` is the small fixture; a real mid-size repository is needed for the rest.

| Workflow | Command sequence | Primary metric |
|---|---|---|
| **W1 — cold read** | Fresh session, `/audit:status`, nothing else | Tokens spent before any work: startup context plus one command |
| **W2 — one task** | `/audit:run <id>` on a task with a known-green gate | Total `output + cache_creation`, main session and subagents separately; per-spawn cold start; executor turn count and inter-turn gaps |
| **W3 — one phase** | `/audit:phase <id>` on a phase with several disjoint tasks | The same, plus sign-off; and the count of reviewer spawns |
| **W4 — plan generation** | `/audit:init` with a fixed scope answer | Explorer cold starts, the discovery payload's share, total to a written manifest |

Every arm is run at least **twice, on different days, with a deliberate gap**, and the spread is
reported. A property seen once inside a timing window is not a property — and cache TTL is exactly
the kind of variable that makes a single run lie.

### 7.3 The measurements that gate a recommendation

| Question | Method | Gates |
|---|---|---|
| Does the reference split actually save what the byte count says? | W2 and W3, before and after Step 2, same target commit | R1 — confirms the byte count reaches the wire |
| What is the executor's inter-turn gap distribution? | W2 and W3: for each executor transcript, the timestamp deltas between consecutive assistant entries; report the median and the share of gaps over five minutes | **R7** — set `cacheTtl: 1h` only if a material share straddles the boundary, and re-measure total spend after, because the community measurement says the naive version backfires |
| What turn count would `maxTurns` have to be to bite? | W2 and W3: the distribution of executor turn counts per completed task | **R6** — pick the bound from the distribution's tail, then re-run W3 and compare spend per *completed task*, not per request |
| Does continuing a retried executor beat respawning it? | Force a red gate on a fixed task; run the retry both ways | **R6** |

### 7.4 The measurement that gates R9

Run W4 twice: all explorers in one message, then the first alone followed by the rest. Compare the
sum of `cache_creation_input_tokens` across the explorer transcripts' first turns. If the staggered
arm's later explorers show cache reads where the simultaneous arm shows writes, the inference holds;
if not, drop R9.

### 7.5 The measurements that are about quality, not tokens

These decide whether a saving is worth taking, and their metric is not tokens.

| Question | Method |
|---|---|
| What does `review.perTask: risky` miss? | Run W3 with `always`, record every `intent.answer`. Re-run the same phase with `risky`. Count the tasks where `always` returned `diverges` or `cannot-tell` and `risky` would not have asked. **A non-zero count is the price of the setting**, and it belongs in the config key's description |
| Does `omitClaudeMd` on the explorer change plan quality? | Run W4 both ways against the same repository. Diff the synthesized findings: count findings present in one arm only, and read them — a finding the conventions would have excused is the cost |
| Does `executor.runsGate: never` change outcomes? | W3 with `own-tests` and with `never`. Compare attempts per task and the recorded gate verdicts. The orchestrator's run is the evidence either way, so the metric is *retries*, not correctness |

### 7.6 The before/after protocol

1. Pin the target repository to a commit and the plan to a copy, so both arms do identical work.
2. Fresh session per arm (`/clear` does not reset a subagent's cache, and a warm parent flatters the
   second arm).
3. Same model and same effort in both arms — each model and most effort levels have their own cache
   ([official](https://code.claude.com/docs/en/prompt-caching#switching-models)), so a mid-run change
   invalidates the comparison as well as the cache.
4. Record per arm: main-session `output`, `cache_creation`, `cache_read`; the same per subagent;
   wall clock; tasks reaching `done`; retries.
5. Report **spend per completed task**, with the spread across repeats. A cheaper request that needs
   another attempt to finish the job is not cheaper.

---

## 8. Sources

**Official — Claude Code documentation**

- Skills, progressive disclosure, the listing, `disable-model-invocation`, `context: fork`, `/skill-doctor` — https://code.claude.com/docs/en/skills
- Slash-command frontmatter — https://code.claude.com/docs/en/slash-commands
- Subagents: startup context, CLAUDE.md, `omitClaudeMd`, `maxTurns`, `experimental.cacheTtl`, model and effort resolution, isolating high-volume operations — https://code.claude.com/docs/en/sub-agents
- Hooks: per-event context visibility, `additionalContext`, `systemMessage`, parallel execution, `updatedInput` — https://code.claude.com/docs/en/hooks
- Prompt caching: the layer model, invalidation, TTL buckets and `subagentPromptCacheTtl`, plugin components that keep the cache, subagents and the cache, fan-out prefix sharing — https://code.claude.com/docs/en/prompt-caching
- Managing costs: reduce token usage, offloading to hooks and skills, CLAUDE.md size guidance, model and effort selection, delegating verbose operations — https://code.claude.com/docs/en/costs
- Plugin reference: directory layout, manifest fields, what loads when — https://code.claude.com/docs/en/plugins-reference
- Context window walkthrough — https://code.claude.com/docs/en/context-window
- Model pricing — https://platform.claude.com/docs/en/about-claude/pricing (via the bundled `claude-api` skill's cached table)

**Community — treated as hypotheses**

- Subagent prompt-cache strategy, measured over ~95 sessions and ~1,800 subagents, including the
  finding that a blanket one-hour subagent TTL is a net loss — https://github.com/anthropics/claude-code/issues/74318
- Startup-context measurement tooling and per-skill listing costs — https://github.com/iops-leo/claude-slim
- Token-reduction practice surveys — https://www.firecrawl.dev/blog/claude-code-token-efficiency · https://buildtolaunch.substack.com/p/claude-code-token-optimization
- Prompt-cache TTL tuning — https://www.matthewswong.com/en/blog/claude-code-prompt-caching-ttl-tuning/

**Measured during the current release run** — this project's own Claude Code transcripts, read
through `message.usage`; agent lifetime versus new cache per call, first-turn cost per agent,
tool-result volume by tool, and the cost of the concurrency spike.

**Measured during this audit** — every byte count and every command output size in section 2, taken
by running the read-only commands named beside them against this working tree.

---

## 9. What I could not verify

Stated so that nothing here is read as settled when it is not.

- **Every token figure is bytes divided by four.** No tokenizer was available and the token-counting
  endpoint was not called. Byte counts are exact; token counts are not, and §7 says how to replace
  them.
- **No end-to-end run was performed.** Section 2 measures inputs, not spend. Every saving in section
  3 is an argument from a measured input, and §7 is how each one becomes a measurement.
- **The community claim that the skill listing has a budget proportional to the context window, and
  that descriptions are dropped when it overflows,** is not something I found in the official
  documentation. What the documentation does say is that the combined `description` and
  `when_to_use` text is truncated per skill, and that every skill in the listing costs context on
  every turn. The recommendation in R4 rests on the second of those, which is official.
- **Whether an `Agent`-tool fan-out shares a cached prefix the way a workflow fan-out does** is
  unconfirmed. R9 is marked as needing measurement for that reason.
- **The session that produced this report ran the installed copy of the plugin, not the working
  tree** — `.claude/state/running-plugin-<session>.json` records the installed version. The two
  guard refusals encountered during the audit came from that copy and do not reproduce against the
  tree, whose decision function answers `allow` with an explicit "destination not established"
  basis. The specific defect is fixed; R10 is about the class, not that instance.
- **The pricing disagreement** between the plugin's bundled `usage.pricing` table and the
  `claude-api` skill's cached table, noted in §2.1, was not settled against the live pricing page.
