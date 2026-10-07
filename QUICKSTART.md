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
gate observes with no plan, warns with a plan and nothing running, and denies while a
phase runs (`/audit:doctor` prints the active tier), so installing this does not start
refusing edits in repos that never opted in.

## 2. Check the install actually works

```
/audit:doctor
```

Read-only, no locks, nothing written. It names the interpreter the hooks will use, the
git root it resolved, and whether the hooks have ever fired here. If anything below
goes wrong, this is the command that says why — so it is worth the ten seconds now
rather than the confusion later.

Two of its rows are worth reading on the first run rather than on the first surprise.

**`plugin files`** answers the question this product owes you before any other: are the
files that run on every tool call the ones that were published? It compares the installed
copy against the checkout it came from. An installation it cannot verify is reported as
*not established* — never as clean.

**`sandbox` and `secret rules`** are about a layer this plugin does not own and leans on.
Its secret guards match the *text* of a tool call and never the I/O, so what actually
stops a secret being read is Claude Code's own sandbox plus a permission deny rule. Both
are opt-in and neither is on by default. The plugin recommends one set for both:
[`plugins/audit/templates/permissions-deny.example.json`](plugins/audit/templates/permissions-deny.example.json).
Merge its `sandbox` key and its `permissions.deny` list into `.claude/settings.json`,
keeping the deny entries in the order the file gives them. What that set costs, and the
exceptions you may want to add, are under *Harden it further* at the end of this page.

If you keep real secrets in this repository, set those before you set anything here —
[SECURITY.md](SECURITY.md) says exactly what the guards do and do not guarantee.

## 3. See what it already cost you

```
/audit:usage --backfill
```

It reads the Claude Code transcripts already in `~/.claude/projects/`, so it works
before any plan exists. It runs no agent and no analysis — a script reads the files
and prints a table, so it costs one ordinary turn — and the only thing it leaves in
your working tree is a self-ignoring ledger under `.claude/usage/`. Every row will
say **Uncategorized** until a plan exists to attribute spend to — see
[Token usage](plugins/audit/README.md#token-usage) in the plugin README for the rest.

## 4. Generate the plan

In a git repository you want audited:

```
/audit:init
```

It interviews you for scope and depth, fans out read-only explorers over the code,
and shows you the phases it proposes **before writing anything**. Approve and it
writes the manifest — a schema-validated JSON file, by default at
`docs/audit/audit-plan.json`. Decline part of it and those phases are parked as
proposals rather than lost.

This is the step that spends real tokens. It is also the step that moves the plan
gate off observing: with a plan and nothing running it warns, and it denies while a
phase runs, because from then on there is a plan to be outside of.

Nothing to audit yet, or just want the guards live before you decide what goes in
the plan? `/audit:init` offers a cheaper first step: the smallest manifest that
validates — one phase, one task, an honestly empty gate or the one you name — in
one call, no interview. Come back and run the full audit above whenever there is
real work to describe.

```
/audit:status
```

Phases, tasks, and what is ready right now. Read it once before running anything —
it is the same view every later command works against.

## 5. Run one task

```
/audit:next --dry-run
```

Shows which task it would pick and why, and mutates nothing. When it looks right:

```
/audit:next
```

One task: a branch, the work, the test gate, one commit. The gate run is recorded — what
ran, when, and what it answered — into a file committed beside the plan, so the report in
the next step can say whether the tests actually ran rather than only that the task is
marked done. It stops after that task and tells you what is ready next, so the first thing
you approve is small enough to judge. `/audit:phase P0` runs a whole phase the same way
once you trust it.

## 6. Read the report

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
- **Harden it further (optional)** — this plugin's guards already refuse a secret read
  (`Read`, `Grep`, `Bash`, an MCP call) whether or not a plan is running, by matching the
  *text* of the tool call. Claude Code's own `permissions.deny` rules match text too — a
  Bash rule is spelling, not a security boundary, and a `Read` deny does not by itself
  reach a subprocess that opens the file indirectly. Only its **sandbox** turns a `Read`
  deny into an OS-level block that every subprocess hits; without the sandbox on, the
  fragment's deny entries catch the same recognised commands this plugin's own guards
  already catch, no further.
  [`plugins/audit/templates/permissions-deny.example.json`](plugins/audit/templates/permissions-deny.example.json)
  is that fragment, the same one "Check the install actually works" points at — merge it
  into your own `.claude/settings.json` if you want the host layer (and, with the sandbox
  on, the OS) to hold it too; it replaces no guard rule, it only adds one.
  If that file already has a `permissions.deny` list, merge this fragment's entries into it
  rather than writing a second list, and **replace** any dotenv rule an earlier version of
  this page suggested (`Read(.env*)`, `Grep(.env*)`) with this fragment's — do not keep
  both. A `Read(!...)` carve-out only reaches rules that come *before* it in the same file,
  so an old `Read(.env*)` left appended *after* this fragment's `Read(!...)` entries would
  not be carved out of by them, and `.env.example` would go back to being denied.

  **What the fragment costs.** Its path entries are gitignore patterns, which Claude
  Code's permission documentation says these rules use (read on 2026-10-06 against CLI
  2.1.291; quoted in
  [`docs/research/guard-ownership-design.md`](docs/research/guard-ownership-design.md)).
  In gitignore matching a pattern with no slash also matches a *directory* of that name,
  so `Read(.env)` and `Read(credentials)` deny everything under a virtualenv created at
  `.env` or a folder named `credentials`; the plain fix is to name the virtualenv `.venv`.
  `Read(*.pem)` denies public certificates and CA bundles as well as private keys; if
  Claude needs one, add a carve-out for that file *after* `Read(*.pem)`, such as
  `Read(!ca-bundle.pem)`. Any carve-out you add goes after the rule it carves from, as the
  fragment's own `Read(!.env.example)` entries do. And `"sandbox": { "enabled": true }`
  does more than make those denies OS-level: the sandbox also confines what a Bash command
  may write, and the parallel phase worktrees this plugin creates sit *beside* the
  repository (`plugins/audit/scripts/git/manage-worktrees.py` names them
  `<repo>-<phase>`), outside it. This repository keeps no dated reading of the sandbox's
  write rules — the design document quotes its read rules only — so check the `/sandbox`
  panel for where writes are allowed before you run phases in parallel with it on.
  [SECURITY.md](SECURITY.md) says which layer holds which guarantee.
- **Depend on it** — [COMPATIBILITY.md](COMPATIBILITY.md): what an upgrade promises
  about the manifest and the config files you own.
- **See it without installing** — the [worked example](examples/) ships a script for
  each UI.
