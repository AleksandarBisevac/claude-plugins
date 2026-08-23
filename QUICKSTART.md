# Quickstart

Install, run one audited task, read the report. One page, in order, and it stops
there — everything else is in the [plugin README](plugins/audit/README.md).

## Before you start

Python 3.8 or newer, reachable as `python3`, `python` or `py`. On Windows, run inside
Git Bash. Nothing else: no `pip install`, no Node, no build step.

## 1. Install

In a Claude Code session:

```
/plugin marketplace add AleksandarBisevac/claude-plugins
/plugin install audit@quality-gates
```

The guard hooks are now active in **all** your projects, by design — but the plan
gate only *observes* until a repository has a plan, so installing this does not start
refusing edits in repos that never opted in.

## 2. Check the install actually works

```
/audit:doctor
```

Read-only, no locks, nothing written. It names the interpreter the hooks will use, the
git root it resolved, and whether the hooks have ever fired here. If anything below
goes wrong, this is the command that says why — so it is worth the ten seconds now
rather than the confusion later.

## 3. Generate the plan

In a git repository you want audited:

```
/audit:init
```

It interviews you for scope and depth, fans out read-only explorers over the code,
and shows you the phases it proposes **before writing anything**. Approve and it
writes the manifest — a schema-validated JSON file, by default at
`docs/audit/audit-plan.json`. Decline part of it and those phases are parked as
proposals rather than lost.

This is the step that spends real tokens. It is also the step that makes the plan
gate start enforcing, because from here on there is a plan to be outside of.

```
/audit:status
```

Phases, tasks, and what is ready right now. Read it once before running anything —
it is the same view every later command works against.

## 4. Run one task

```
/audit:next --dry-run
```

Shows which task it would pick and why, and mutates nothing. When it looks right:

```
/audit:next
```

One task: a branch, the work, the test gate, one commit. It stops after that task and
tells you what is ready next, so the first thing you approve is small enough to
judge. `/audit:phase P0` runs a whole phase the same way once you trust it.

## 5. Read the report

```
/audit:report
```

Renders one self-contained HTML file plus a Markdown twin — collapsible phases,
search, filter, Save-as-PDF. No server and no assets: open it in a browser, mail it,
or publish it as a link with `--share`.

That is the loop. `/audit:next` and `/audit:report` are the two you will keep typing.

## If something goes wrong

`/audit:doctor` first — it diagnoses the setup rather than guessing at it. The
[plugin README](plugins/audit/README.md#troubleshooting) has the failure-by-failure
list, including what to do in a repository with no test suite and how to work in a
monorepo where git lives in a subdirectory.

## Where to go next

- **Tune it** — [configuration](plugins/audit/README.md#configuration-claudeauditconfigjson),
  or `/audit:panel` for the same settings as a form in your browser.
- **Trust it** — [what is enforced and what is merely
  followed](plugins/audit/README.md#what-is-enforced-and-what-is-followed), and
  [SECURITY.md](SECURITY.md) for what the guards do *not* guarantee.
- **Depend on it** — [COMPATIBILITY.md](COMPATIBILITY.md): what an upgrade promises
  about the manifest and the config files you own.
- **See it without installing** — the [worked example](examples/) ships a script for
  each UI.
