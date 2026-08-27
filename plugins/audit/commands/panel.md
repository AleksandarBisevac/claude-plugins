---
description: 'Audit pipeline: open / stop / check a local control-panel UI to visually manage .claude/audit.config.json and the manifest''s composition levers (reviewSkill, per-task skills/models, buildCommands) — with live validation and discovery of the skills & agents available in this repo + globally. Ephemeral, on-demand; a per-project pidfile keeps it discoverable and stoppable.'
argument-hint: '[stop|status] [--port <n>]'
allowed-tools: Read, Bash
---

# /audit:panel — the control panel (open · stop · status)

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first (read-only preflight
1–2; no lock — the panel itself takes the manifest lock only when it *writes* the manifest,
and refuses if one is held). Let `PANEL="${CLAUDE_PLUGIN_ROOT}/scripts/panel/panel-server.py"`.

**Dispatch on `$ARGUMENTS`:**

- **`stop`** → run `python3 "$PANEL" --project "$(pwd)" --stop` and print the result.
- **`status`** → run `python3 "$PANEL" --project "$(pwd)" --status` and print the result.
- **otherwise (open)** →
  1. Launch it **detached** so it survives this turn, passing `--port <n>` through from
     `$ARGUMENTS` if given. **Stderr goes to a per-project log, never to `/dev/null`** —
     see *Why the launch keeps its stderr* below; the append (`2>>`) and the log's name
     are both load-bearing, so copy the two lines as they stand:
     ```
     mkdir -p "$(pwd)/.claude"
     nohup python3 "$PANEL" --project "$(pwd)" >/dev/null 2>>"$(pwd)/.claude/audit-panel.log" &
     ```
  2. Wait ~1s, then read the live URL back:
     ```
     sleep 1; python3 "$PANEL" --project "$(pwd)" --status
     ```
  3. Tell the user **exactly what `--status` said**, and nothing it did not say. It reports
     one of three states and they are not interchangeable:
     - `panel RUNNING: <url> (PID n)` → the panel is up; their browser opens automatically.
       **Stop it anytime with `/audit:panel stop`** (or `/audit:panel status` to check).
       It's per-project — launching again just points at the already-running one, so it
       never leaves an untracked process behind.
     - `panel not running` **with** an `its last launch left this on stderr …` line → the
       launch FAILED and that line is the reason. Report the reason; do not report a launch.
     - `panel not running` with no such line → nothing was started and nothing was recorded.
  4. If `--status` prints `stop and relaunch to pick it up`, say so: the panel that is up
     assembled its page from an older build of the plugin, and the controls that shipped
     since are missing from it until it is stopped and started again.

### Why the launch keeps its stderr

A detached launch that discarded stderr left a failed launch looking **exactly** like a
launch that succeeded and was then stopped — no pidfile, no message, nothing on record
(F99). The log is emptied by the server itself once it is actually listening, so anything
left in it belongs to a launch that never got up, and `--status` prints its last line.
`.claude/audit-panel.log` is gitignored by the panel itself, beside the pidfile.

Two things are **expected and harmless** under Claude Code's sandbox, so do not chase them
and do not report them as failures:

- `nice(5) failed: operation not permitted` on launch — `nohup` asking for a priority the
  sandbox declines. The server does not need it and starts normally.
- the stop signal refused on the first attempt from inside the sandbox. The server stops
  correctly; re-run `/audit:panel stop`, or stop it from an unsandboxed shell.

**Prefer a visible terminal window?** (foreground, `Ctrl-C` to stop) — tell the user they can
run it themselves; in a Node repo `npm run panel` / `npm run panel:stop` is the shortcut,
otherwise `python3 "$PANEL" --project "$(pwd)"`.

## What the panel does (summary for the user)
- **Settings** — a form over the **whole** of `.claude/audit.config.json`, in five groups:
  *Paths & gate*, *Write guards*, *TDD reminder*, *Usage & pricing*, *Audit trail* — including the rate
  table, the cost bands and the TDD globs, which previously had no control at all. Each field
  is named by what it does with its JSON key beside it and an ⓘ hint; an empty field removes
  the key rather than writing a default. Regexes and the band pair are checked as you type;
  the save is decided by `validate-config.py`, which refuses invalid input, and writes
  atomically. Every "set X in the config" notice elsewhere in the panel links here.
  The plan gate's tier is one select (**How hard the gate pushes**, v0.34): its preset also
  reads the legacy `enforce` flag, and choosing a tier writes `planGate` while deleting
  `enforce` — one statement of the gate's tier, not two keys contradicting each other.
- **Plan & models** (route `comp`) — set `meta.reviewSkill`, per-task `skills[]` / `model`, per-phase
  `review.model`, `meta.buildCommands` — via an autocomplete **populated by discovery** of
  the skills & agents actually available (project `.claude/`, `~/.claude/`, installed
  plugins). The model fields carry the same autocomplete with three named sources (v0.34):
  models the manifest already uses, models the rate table prices, and models the token
  ledger has actually recorded — the last is what a typo'd model id looks like from the
  spend side. Every autocomplete searches descriptions as well as names, and a long list
  ends `…N more — keep typing` rather than cutting off silently.
  Writes back **only** these fields, validates via `validate-manifest.py`, and
  **refuses while an `/audit` run holds a lock** (the index or any phase — see conventions →
  Concurrency lock). Never touches phases/tasks/bugs structure — use `/audit:task`,
  `/audit:bug`, `/audit:run` for that.
- **Policy** — the capability switchboard over the `policy` block (v0.30): which **skills**,
  **subagents** and **MCP servers** may be used here. One row per capability the project can
  actually reach, carrying the verdict the guard hook would give it **and the reason** — computed
  by the same `_policy.resolve` the hook calls, never by the browser, so the preview cannot
  disagree with the enforcement. A row's switch writes an exact name into `allow` / `deny`; the
  **Rules as written** table below it shows the block itself, in the order the verdict is decided
  (deny before allow, project before area), which is where a glob like `code-*` is added and
  removed and where you can see what it matches today. Area columns come from the plan's own tags
  and say which are **live** (that area has work in progress, so its rules apply) and which are
  **dormant**. Audit's own commands, skills and agents are shown **locked** — the panel refuses to
  write a policy denying them, and so does the validator. Above all of it, the honest state: inert,
  turned off, enforcing — or *active but never seen to run here*, which is what a missing
  guard marker means and what `/audit:doctor` warns about. It saves through the same confirm
  dialog and journal as everything else.
- **Areas, over the API only (v0.28).** `GET /api/areas` returns the `meta.areas` registry plus
  every tag the phases actually use — which are registered, which are typos, which roots are
  missing — and `PUT /api/areas` replaces the registry wholesale through the same writer, lock,
  validation and change echo as Plan & models. There is **no form for it yet**; say so rather than
  sending someone looking for a tab that is not there. Edit `meta.areas` by hand, or let
  `/audit:init` write it.
- **Help, over the API only (v0.31).** `GET /api/help` serves every config and manifest field
  with the description its **schema** gives it — extracted at request time, so the panel and the
  file your editor validates cannot say different things — plus four concept pages (how the plan
  gate grades, how an area resolves a reviewer, how a policy reaches a verdict, what the journal
  proves) and the `audit:guide` agent's card. There is **no drawer for it yet**; say so rather
  than sending someone clicking for an ⓘ that is not there. For a question the schema does not
  answer, ask for the `audit:guide` subagent by name — it reads the plugin's own docs and cites
  them, and it is read-only.
- **Nothing is written without showing you what** — on both Settings and Plan & models. Save
  opens a dialog listing every change as `P1.2 · model · sonnet → opus`, together with any
  phase that is running elsewhere *right now*; Cancel writes nothing and keeps your edits.
  **Discard** says how many changes it would throw away and is dead while there are none,
  closing the tab with unsaved work asks first, and the server recomputes the change list
  against the file it is about to write and sends it back — so if a second tab or an
  `/audit` run moved the file under you, the save says so instead of quietly reassuring you.
  The toast reports how many changes landed. A landed save also leaves a **✓ saved** card
  that dissolves after five seconds; a refused save leaves a card that does not — bold
  title, the findings that refused it, its own dismiss × — because a refusal must outlive a
  glance away (v0.34). The topbar names the identity the write is
  recorded under (`viewing as …`, resolved exactly as the token ledger resolves a spender —
  see `usage.authorMode`), and Usage has a **my spend** chip that filters on that same name.
  The panel also refreshes **itself**: a fingerprint of the config, the manifest, its shards,
  the usage ledger and the evidence ledger rides the run-status poll, and when a file moves
  on disk clean views re-render
  within a few seconds — a form holding unsaved edits is left alone and gets a persistent
  notice instead (Save is still checked against the file on disk; Discard reloads it), and
  refreshes hold while any dialog is open.
- **Overview** — the live rollup + validation status, as something you can steer by: task and
  bug **status strips** that are both the legend and the filter (press one to scope the phase
  list), search over id / title / area / desired outcome, sort by plan order, progress or
  status, optional **group by area** from `meta.areas`, each phase row showing its desired
  outcome and opening that phase in Plan & models, and a **Ready now** card with the exact
  `/audit:run <id>` to copy. Bug statuses here are *effective* — a bug materialized into a task
  reads `Fixed` once that task is done, which is what the counts above them use. A **Plan
  gate** card (v0.34) names the tier in force and its source (`planGate`, legacy `enforce`,
  or the graded ladder), shows whether a bypass is armed right now, and lists the latest
  gate events from `<logsDir>/plan-gate-events.jsonl` as they land — refreshed by the same
  poll that tracks running phases.
- **Recorded test runs** — inside a phase's detail on Overview, and read-only like the rest of
  that tab: the panel never records a run and never writes a pointer. Two lines, **labelled
  apart** because they are two measurements: `phase sign-off` is the run the gate this phase
  signs off with last recorded, and `tasks` counts the phase's tasks by what each one's *own*
  last run said. One badge for both would claim a measurement nobody made. The task table then
  ends with a `tests` column, in the report's column order, so the two tables read the same
  way. A badge is a **button only where there is a run to open** — behind the silences there
  is nothing, and a button onto an empty box is a promise the page cannot keep; opened, it
  gives the run id and stamp, the attempt, the duration, how much ran, the tree / coverage /
  check-count **bases as sentences**, and a row per step (step, exit, checks, took, outcome).
  A run that recorded no steps says so rather than drawing an empty table.
  Every way there is no run gets its own answer, and they are not one grey blob:
  **`No gate configured`** (nothing could have run — neither this subject nor its phase
  declares a gate, which is answered before the boundary is consulted), **`No evidence`**
  (a gate is declared and nothing has been recorded, which is never *failed*),
  **`Before recording`** (the work finished before this plan could first have recorded
  anything, so the `no-test-evidence` gate **excuses** it — the sentence carries the
  boundary's own basis, and without this word a plan adopted mid-flight would show a wall
  of `No evidence` while the gate reported green), **`Completion undated`** (done, no run,
  and no completion stamp to place it against that moment — the gate **fails** this one and
  the repair is the stamp, not a gate run), **`Pointer without evidence`** (the plan names a
  run the ledger here does not hold — and that sentence names how many ledger files were read
  and how many lines could not be parsed, so a record that was never written is not confused
  with one whose rows are torn, and it quotes the verdict the plan had cached), and otherwise
  the verdict the **ledger row** carries — never the plan's cached copy of it. Which class a
  silence falls in is computed on the server by the same function the gate buckets its verdict
  with, and shipped on the row: the browser renders a fact rather than comparing two stamps of
  its own. A word this build does not know is shown as itself rather than folded
  into `failed`; the manifest schema leaves that enum open.
  Unlike the report, which omits the whole surface on a plan that points at no run, the panel
  draws these lines on every plan — this is the live view, and *nothing has run yet* is the
  answer an operator opened it for. It is also why the refresh fingerprint stamps the
  **evidence directory** and not only the shards: a gate finishing mid-phase normally moves a
  pointer in its shard, which is watched already — but a run recorded while another session
  holds the phase lock writes the row and has its pointer refused, so nothing in the plan
  moves at all, and watching the plan alone would leave that badge waiting for a manual
  reload.
- **Usage** — what the plan cost, recomputed in the browser on every filter change. KPI tiles
  carry a sparkline and a trend against the window before (all-time compares the ledger's last
  30 days with the 30 before them — anchored on the data, so a finished project still shows a
  trend — and the chip names both periods). Filter by model, author, phase, task, agent,
  attribution or **area** (the select appears only when the plan tags areas, offers `untagged`,
  and joins spend to its phase's tags at read time — free text finds a tag too), by free text
  over ids *and* titles, and by an absolute from/to window that
  writes the same filter a click on the chart does. The chart bins by day, week, calendar month
  or quarter as the span demands; a **bin** select forces day/week/month when a choice fits the
  chart, and the presets include **last 12 months**. A **Monthly** card appears once the ledger
  spans two calendar months: its ledger half follows the filters, its plan half (tasks done,
  bugs, fixed, merged) is server-computed and project-wide — the crumb says so — and clicking a
  month scopes the view to it. Selecting an author adds a **person header**: their all-time
  share, models, phases and tasks touched with a status split, active range — deliberately not
  following the filters, since the tiles below already answer the filtered question.
  **Export CSV** downloads exactly the rows
  behind the view, with the span and bucket resolution in the filename. Every scope shows as a
  chip you can take off; `Esc` pops the last one. Filters **persist** (v0.34): the state
  rides in the URL fragment (`#/usage!au=…`), so a filtered view is a share link the way the
  report's is, and it is remembered per repo across reopens — hash wins over the remembered
  state, and clearing the filters clears both. The **last 7 / 30 / 90 days** presets mean
  exactly that — they count back from today, not from the last day recorded — so on a plan that
  finished months ago they can select nothing. When that happens the tab says which window it
  asked for, when the ledger actually ends, and offers the all-time view; more generally, an
  empty result names the one filter emptying it rather than only offering to clear them all.

Safety: binds `127.0.0.1` only, requires a per-launch token on every API call, and refuses
any write whose path escapes the project directory. Ephemeral — it runs until you `stop` it.
