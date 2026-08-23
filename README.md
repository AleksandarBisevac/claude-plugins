# quality-gates

[![ci](https://github.com/AleksandarBisevac/claude-plugins/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/AleksandarBisevac/claude-plugins/actions/workflows/ci.yml)
[![license MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![zero dependencies](https://img.shields.io/badge/dependencies-0-blue)](CONTRIBUTING.md#hard-rules)

A [Claude Code](https://code.claude.com) plugin marketplace with one theme:
**enforced** engineering discipline — plan gates, test gates, sign-off gates,
secret guards. The guards are deterministic hooks; the pipeline they govern is an
orchestrator prompt — [which is which, row by row](#what-is-enforced-and-what-is-followed).

### ▶ The gate, refusing

The plan gate denying an edit no task covers, while a phase is running. Every line is
this plugin's real output — `audit-status.py` renders the plan, `require-plan.py` is fed
the same `PreToolUse` payload Claude Code sends it, and its refusal is what you see.
Re-record with `python3 tools/capture-demo-gif.py`.

![The plan gate: an edit inside the plan passes silently, an edit outside it is refused with the file named and a way out](docs/screenshots/demo-gate.gif)

### ▶ See it

A live, interactive audit report (search, filter, collapsible phases, Save-as-PDF) — nothing to install:

**[aleksandarbisevac.github.io/claude-plugins](https://aleksandarbisevac.github.io/claude-plugins/)** · or read the [worked example](examples/).

[![An audit report: summary, progress, phases and bug list](docs/screenshots/overview.png)](https://aleksandarbisevac.github.io/claude-plugins/)

## Plugins

| Plugin | What it does |
|---|---|
| [**audit**](plugins/audit/README.md) | Manifest-driven, model-aware, test-driven audit/fix pipeline: `/audit:status`, `/audit:run`, `/audit:phase` (and siblings) execute phases/tasks from a schema-validated JSON manifest (branch-per-phase, per-task model + skills, red-first TDD bug fixes, gated sign-off), `/audit:init` generates the manifest from a multi-agent codebase audit, `/audit:layout` switches the manifest between one file and one file per phase — the sharded shape gives **parallel phases across git worktrees** (fewer tokens per run, conflict-free merges) and the command goes back the other way too, a `/audit:panel` control panel manages config + composition in the browser, and guard hooks enforce plan-first development, secret safety and a TDD nudge. |

## What is enforced and what is followed

Two halves, and they hold in different ways. The **guards are hooks**: a `PreToolUse`
handler returns a decision and the tool call does not happen. The **pipeline is a
prompt**: `plugins/audit/reference/orchestrator.md` is the execution core, read by the
model on every `/audit:*` call, and its invariants are instructions rather than
guarantees. Both columns below are the real thing; only the left one holds when the
model does not comply.

The left column has two kinds of row. Most are a hook refusing a tool call **before** it
happens. The last few are a script returning an exit code **after** it did —
`scripts/governance/verify-invariants.py`, which re-derives those rules from git, the
phase shard, the journal and the usage ledger, and which Phase sign-off and
`/audit:status --gate --fail-on invariant-breach` both run. A rule nothing can refuse in
advance is still enforced if a breach cannot pass a gate; a rule nothing checks at all is
policy, and that is what the right column is.

| Enforced by a hook (before) or a script (after) | Followed from `orchestrator.md` |
|---|---|
| Secret file **contents** — never read, directly or indirectly | Human confirmation before a `reset` / `rebase` / `clean` |
| Env values and token variables — never dumped | `risk: "high"` waits for a human before committing |
| Shell writes into source files no task covers | Revalidate the manifest after **every** write |
| Commits the manifest records — never orphaned | `attempts >= maxAttempts` sets `blocked` |
| Skills, subagents and MCP tools — the project's `policy` | An infrastructure failure burns no retry |
| Auth tokens — never logged | Red-first TDD where `tests.mode` asks for it |
| The project's own banned patterns, per path | The executor never commits; the orchestrator does |
| The plugin's own files — not editable by the model | Run only what the readiness rule allows |
| The plan-first bypass — armed from human prompts only | Parallel only on disjoint file sets |
| The audit trail — append-only, no hand edits | Take the narrowest lock, and stop on exit 3 |
| Non-trivial edits — planned, or explicitly opted out | Sign-off in strict order: review → gates → boot |
| Manifest writes against another live session's lock | `--ff-only` into the resolved parent, never a rebase |
| Every plan and config write — journalled, hash-chained | `git -C <gitRoot>`; gate commands from the project dir |
| Token spend — attributed to a phase and a task | Spawn the executor with the task id in its description |
| Unaccounted shell writes — reported in-band | Skills invoked before any code is written |
| Source changed with no test — nudged |  |
| Explorer cannot write, reviewer cannot edit, executor has no web tools |  |
| The manifest — referentially validated, by exit code |  |
| *(after)* A task commit staged that task's files, its phase's shard and the journal — never the index |  |
| *(after)* No `push` reached a remote from the phase branch |  |
| *(after)* No forced update and no `git stash` touched the phase branch |  |
| *(after)* A `risk: "high"` task ran on neither a declared nor a metered `haiku` |  |
| *(after)* `phase.baseRef` is on the branch the phase forks from |  |

The right column is not one thing. Some of it is **verifiable after the fact** and simply
has no checker yet; some of it is verifiable by **nothing at all** — a human confirmation
that never happened leaves no trace, and a reverted `attempts` increment is the same
number as one that never happened. Which is which matters before you rely on a row, so the
[plugin README](plugins/audit/README.md#what-is-enforced-and-what-is-followed) gives the
per-rule version of both tables: for each enforced rule, the hook or script and the
decision it returns; for each invariant, where it is written and what evidence would catch
a breach. [SECURITY.md](SECURITY.md) has the fail modes and the accepted bypass classes.

## Install

```
/plugin marketplace add AleksandarBisevac/claude-plugins
/plugin install audit@quality-gates
```

> The guard hooks activate in **all** your projects, by design — but the plan gate is
> **enforced once you have a plan, observing before that**, so installing it does not
> start denying edits in repos that never opted in. See
> [installing arms global hooks](plugins/audit/README.md#installing-arms-global-hooks).
> Requirements: Python 3.8+ reachable as `python3`, `python` or `py` (CI verifies on 3.12)
> (on Windows: run inside Git Bash).

## Quickstart

**Start here — it costs nothing and needs no setup:**

```
/audit:usage --backfill    # reads transcripts already on disk → your own past spend
```

No manifest, no agents, no tokens spent: it scans the Claude Code transcripts already
in `~/.claude/projects/` and prints what this repo has cost you so far, broken down by
model, author and agent. Everything will read as **Uncategorized** — that is the
point. Attributing spend to *phases and tasks* is what the rest of this does, and it
is the comparison a plan-driven pipeline can make that a date-range dashboard cannot.

Then, in any git repo you want to audit:

```
/audit:doctor          # is the setup healthy? interpreter, git root, config, gates
/audit:init            # interview → generates a schema-valid audit manifest
/audit:status          # see phases, tasks, bugs, and what's ready now
/audit:layout sharded  # (optional) one file per phase → parallel-safe phases across worktrees
/audit:panel           # open the browser control panel to tune config + composition (open/stop/status)
/audit:phase P0        # run the first phase: branch → tasks (red-first TDD) → gated sign-off
/audit:report          # render the HTML + Markdown report (--share publishes it to a link)
/audit:usage           # the same spend view — now attributed to phases and tasks
```

`/audit:init` interviews you (scope, dimensions, size) and writes the manifest;
everything else reads and updates it. The report is one self-contained file
(open it in a browser, or **Save as PDF**). See the [worked example](examples/)
for what a manifest and its report look like, or the [plugin README](plugins/audit/README.md)
for the full command reference.

Want to try the two UIs before installing anything? The example ships a script
for each — `examples/panel.sh` opens the control panel on it, `examples/report.sh
--open` re-renders and opens the report. No install, no session, no dependencies.

## This repo, dogfooded

`docs/audit/audit-plan.json` is this repository's own roadmap written as an
`audit` manifest — CI validates it with the plugin's own validator on every
push. Open it for a real-world example of phases, tasks, reciprocal bug links
and a fileIndex.

## Docs

- [**Enforcement over persuasion**](docs/essays/enforcement-over-persuasion.md) — why the
  guards are hooks and pinned tool lists rather than firmer wording, the two ways this repo
  got that wrong, and what enforcement cannot do
- [Plugin README](plugins/audit/README.md) — install, quick start, configuration, extending
- [CHANGELOG](CHANGELOG.md) · [SECURITY](SECURITY.md) — threat model & what the guards do NOT guarantee · [CONTRIBUTING](CONTRIBUTING.md)
- [PLUGIN-BUILD-GUIDE](PLUGIN-BUILD-GUIDE.md) — how this plugin is put together, file by file

License: [MIT](LICENSE)
