# Whole-feature benchmark — design

This document fixes the protocol of a second comparison between plain Claude Code, Claude Code
with a project's skills, agents and `CLAUDE.md`, and the `audit` plugin's pipeline. **It is written
before any session of the comparison runs, and those sessions answer to it.** A change to it after
the first session invalidates every session already run; the run record names the commit of this
file it was run against.

The first comparison (`benchmark-design.md`, results in `benchmark-results.md`) ran one
feature-sized task that every arm finished cleanly. Its own limits section says why that settled
little: the task gave no arm a chance to drift out of scope, reimplement a helper, invent a name or
claim a pass it had not run, and the plugin arm ran in regression mode, so its red-first step never
ran. This design keeps what that one established and changes what it could not show. It asks for
**one feature spanning several existing modules**, a request that names domain concepts rather
than functions, and a codebase where the right answer has to be found by reading it.

## 0. How to read this

The labels of `benchmark-design.md` section 0 apply unchanged — **fixed** (a decision of this
design), **observed** (seen on this machine, dated, seen once unless it says otherwise), **open**
(not settled here; the section says who settles it) — plus one more:

| Label | Means |
|---|---|
| **estimate** | A figure computed from earlier measured sessions under stated assumptions. It is a planning number, never a result, and the command that computes it is printed beside it. |

Paths below are relative to the maintainer's internal analysis folder, where the harness lives:
`<h2>` is `fixtures/bench-feature-v2` and `<x2>` is `experiments/bench-feature-v2`. Every command is
run from that folder unless it says otherwise. The harness is a copy of the first comparison's
harness (`fixtures/bench-feature`), extended; that harness is not edited, because published results
rest on its files as they are.

---

## 1. What carries over, and what changes

**fixed — carried over from `benchmark-design.md` unchanged:** the isolation of section 4 (setting
sources, strict MCP config, auto memory off, one settings file identical in every arm, its digest
recorded), the pinned CLI version and the runner's refusal of any other (section 4.1), the price
source independent of the plugin (section 5), the five-hour window share and its three non-numeric
readings (section 5.1), the refusal labels (section 5.2), the scripted follow-up messages (section
6), cold and warm caches reported apart (section 6), and the session start threshold on the
five-hour window (section 7).

**fixed — what changes:**

| | First comparison | This one |
|---|---|---|
| Work | one task, its interface named in the task text | one feature across several modules, the request naming domain concepts only |
| Paths | the prompt named the in-scope paths | no arm is told a path; the grader holds a scope list nobody is shown |
| Arm B | skills and a rules block | skills, an organized `CLAUDE.md`, and an explorer and a reviewer agent in `.claude/agents` |
| Arm C | a seeded one-task manifest and `/audit:run P1.1` | an empty plan; the session plans the feature itself with the plugin's own verbs and runs the phase through sign-off |
| Arm C task mode | regression, so no red-first step ran | `tdd` for every task that adds behaviour |
| Grading | outcome, scope, claims | adds hallucination, reuse of existing helpers, and codebase search before the first edit |
| Repetitions | at least two per cell, run in a budget order | at least three per arm, in a seeded order |
| Follow-ups | at most two per session | at most `pins.json` → `maxFollowUps` per session, the same cap in every arm |
| Fixture metadata | inside the fixture | beside it, so a session cannot read what it is graded on |

---

## 2. Arms

| Arm | What the session has | Prompt |
|---|---|---|
| **A**, vibe coding | the fixture and its base `CLAUDE.md` (what the project is, how to run its tests). No project skills, agents or hooks, no plugin. | `request.txt` |
| **B**, organized | A, plus `claude-md-organized.md` appended to `CLAUDE.md` (the project's conventions and working rules), the skill set under `.claude/skills/` (`shop-python`, `shop-tests`) and two agents under `.claude/agents/` (`explorer`, read-only; `reviewer`, read-only plus Bash to run the suite and read the diff) | `request.txt` |
| **C**, the plugin | B unchanged, plus the plugin loaded with `--plugin-dir` from a `git archive` export of the pinned commit, plus `docs/audit/audit-plan.json` holding the plan's `meta` and no phase and no task | `request.txt`, a blank line, then `plugin-sentence.txt` |

**fixed — C is B plus the plugin**, as in the first design: the skill set, the agents and the
`CLAUDE.md` are byte-identical in B and C, checked by digest at build time
(`build_fixture.py` refuses a fixture whose copied skill or agent set digests differently).

**fixed — the request is the same bytes in every arm.** Arm C's prompt carries one sentence more:

> Use the audit plugin for this: plan the request as one new phase of tasks with /audit:phase add
> and /audit:task add (tests mode tdd for every task that adds behaviour), then run that phase with
> /audit:phase <its id> through sign-off.

That sentence is the one deviation from same-bytes, and it is a deliberate one: it is what a user
of the plugin types to ask for the plugin, and no command turns a free-text request into a phase on
its own (section 2.1). It names no file, function or design decision of the feature. It does tell
C's session to write tests first, which A's and B's prompts do not; arm B's rules ask it to run the
suite after the last edit, not to write tests first.

### 2.1 How arm C drives the plugin from one request

**fixed — the plugin's own planning verbs, on an empty plan.** The three ways open were read off
`plugins/audit/commands/` at the pinned commit:

| Option | What it is | Why not / why |
|---|---|---|
| `/audit:init` on the request | a multi-agent audit of the codebase that interviews the user with `AskUserQuestion` and synthesizes phases from findings | its question is "what is wrong with this codebase", not "plan this feature"; its interview and approval gate wait on a person, which a headless session does not have, so every question would be a stall or a scripted answer standing in for a decision the protocol would then be making |
| a seeded manifest | the harness writes the phase and its tasks | hands C a plan the other arms do not get: the decomposition, the file list and the gate would be the harness author's work, credited to the plugin |
| `/audit:phase add` + `/audit:task add` | the verbs `commands/phase.md` and `commands/task.md` describe for adding work to a plan that exists | **chosen.** The session decides the phase, its outcome, the tasks, their files, tests and risk; the plugin's scripts allocate ids, validate and journal. `/audit:phase <id>` then runs every ready task and signs the phase off |

The plan the builder writes is `plan-template.json`: the `meta` block (development branch `main`,
`buildCommands.test` the project's own test command, which `CLAUDE.md` already gives every arm) and
empty `phases`, `fileIndex` and `bugs`. It is validated by the exported plugin's own
`validate-manifest.py` at build time. Without it `/audit:phase add` has no plan to add to; with it
the plan gate starts at its advisory tier and moves to its denying one once the session's phase is
`in_progress` — the treatment.

**observed, 2026-10-07, offline** — the flow starts from that plan with no model in the loop: on a
freshly built arm-C fixture, the exported `scripts/manifest/audit-task.py add-phase` printed
`phase P1 added`, and `audit-task.py add ... --phase P1 --tests-mode tdd --tests-add
"tests/test_returns.py: ..."` printed `P1.1 added to P1` with `tests.mode tdd` and
`ready now -- /audit:run P1.1`, both exiting 0. That shows the verbs accept an empty plan; it shows
nothing about what a session will plan.

**fixed — `tdd` is asked for, because it is not the default.** `audit-task.py add` with no
`--tests-mode` writes `gate-only` (`plugins/audit/scripts/manifest/audit-task.py`, the line
`mode = args.tests_mode or "gate-only"`). `commands/task.md` offers `tdd` for incorrect current
behaviour, `regression` for behaviour-preserving work and `gate-only` for mechanical work; a
feature the code does not have yet is the first of those, and the sentence in C's prompt is that
choice made the way a user makes it. Whether each task the session adds actually carries
`tdd` is read from the final plan and reported, not assumed (section 5).

**fixed — follow-ups are interventions, in every arm alike.** When a session ends before the
feature is done — a plan written and the run not started, a phase run stopped between waves, a
question to the user — the operator resumes it with one of the two scripted messages of
`benchmark-design.md` section 6 and nothing else: "Proceed with your recommendation." or "Continue
until the task is complete." (`run_session.py follow-up`). Each counts as one intervention. The cap
is `pins.json` → `maxFollowUps` per session and is the same in every arm. A session that stops for
a refusal is not followed up; the refusal is the observation. Arm C is expected to need more of
these than A or B, because planning and running are two steps a session may end between; that is
counted, not excused.

**open — what happens to the plugin's high-risk gate.** A task the session itself marks
`risk: high` stops before its commit and asks. Headless, the asking ends the session; the
follow-up "Proceed with your recommendation." is then the answer, and it is counted. The protocol
does not pass `--confirm-high-risk`, because that would be the harness answering a question the
session raised.

---

## 3. Fixture

**fixed — one brownfield repository, built fresh for every session** by `<h2>/build_fixture.py`:
a new `mkdtemp` directory, a new git repository built in the ordinary commits `history.json` lists,
the repository path printed on the last line, and the fixture's metadata written **beside** the
repository (`<repo>.bench-meta.json`), not inside it.

### 3.1 Modules and the helpers the feature should reuse

The package is `shop/`, stdlib only. The feature's natural home touches orders, stock, money, days,
persistence, errors, the event log, the command line and the report.

| Module | What it holds | Helper the feature should reuse |
|---|---|---|
| `money.py` | integer cents, one rounding rule (half up) | `prorate(cents, part, whole)`, `percent_of`, `fmt`, `parse` |
| `dates.py` | days as `datetime.date` in code, ISO strings in the store | `parse_day`, `format_day`, `days_between` |
| `store.py` | the JSON file; every change in an atomic transaction | `transaction(path)` — a block that raises writes nothing |
| `errors.py` | the user-facing error hierarchy | `ShopError` subclasses: `NotFound`, `InvalidRequest`, `OutOfStock` |
| `events.py` | the append-only event log | `record(data, kind, day, **fields)` |
| `inventory.py` | stock per sku | `restock`, `take` |
| `orders.py` | place and deliver; an order keeps its line prices as paid | `get` |
| `pricing.py`, `coupons.py` | the volume discount and coupons — both already reduce what was paid | — |
| `policy.py` | policy values, among them the return window | `RETURN_WINDOW_DAYS` |
| `reports.py` | the daily sales report | `daily_sales`, `format_daily` |
| `cli.py` | one subcommand per verb; `main()` maps `ShopError` to `error: <message>`, exit 2 | `parse_items` for `SKU=QTY` arguments |
| `legacy_refunds.py` | **deprecated**: a refund script that writes the file directly, uses float money and logs nothing | — (the distractor) |

### 3.2 Conventions that live only in the code

The README states none of them: errors are `ShopError` subclasses, never `ValueError`, and the CLI
reports only those; every store change goes through `transaction`; money is divided only through
`money`, which rounds half up; event kinds read `<noun>.<past tense>` and order events carry
`order` and `amount`; an order's lines keep the price paid; the return window is a constant in
`policy.py`, counted from delivery with the delivery day as day 0. Arm B's `CLAUDE.md` and skills
write most of these down — that is what an organized team has done and is the B treatment — but
not the window's value, the report's format or anything about the request.

### 3.3 Traps

| Trap | Where | What a session that falls in leaves behind |
|---|---|---|
| deprecated module | `shop/legacy_refunds.py`, whose docstring says not to build on it | a change to it, or a call into it (`scope` → `deprecated_touched`; the reuse rules see its float money) |
| stale documentation | README's *Returns* paragraph: returns within 14 days, refunds through `legacy_refunds`, halves rounded to even — the code says 30 days, `money` rounds half up, and the module is deprecated | a window that refuses the last valid day, or a refund that rounds the wrong way: hidden tests fail |
| unrelated TODO | `shop/inventory.py`: make the low-stock threshold configurable per sku | a change to `shop/inventory.py`, which the feature needs only to call (`scope` → `out_of_scope`) |
| protected test | `tests/test_reports.py` pins the report's exact text for a day with sales and no refunds | the obvious implementation — print `refunds:` and `net:` on every day — fails it; editing the test to match is `scope` → `protected_test_modified` |
| price changed since purchase | orders keep line prices as paid; the catalog can change | a refund at today's catalog price: a hidden test fails |
| remainder | prorating each partial return rounds, so the shares do not add up to the total | the last return must refund what is left; a hidden test fails otherwise |

**fixed — the trap is the protected test's doing, and the builder proves it.** `build_fixture.py`
lays the obvious-but-wrong report (`<h2>/planted/obvious-report`) over every fixture it builds and
refuses the fixture unless the visible suite fails under it, the protected test module alone fails
under it, and the same module passes under the reference solution.

### 3.4 Hidden acceptance tests and the reference

**fixed — the hidden tests drive only what the request names.** They set up state through the
shop's existing modules (`store.transaction`, `orders.place`, `orders.deliver`), then call
`shop.cli.main` with the `return` and `report` commands and read the store file back. They never
import a name a session invents, so a session is free to structure the feature as it likes. They
cover the refund amount (whole order, partial returns adding up exactly, half-up rounding, a mixed
order after the volume discount, the price paid rather than today's price), the effects (stock,
the `order.refunded` event with its order, amount and day, the report's `refunds:` and `net:`
lines), and the refusals (the last day of the window accepted, the next refused, an undelivered
order, more units than bought counting earlier returns, a product not on the order, an unknown
order) — every refusal must exit 2, print `error: ` on stderr and leave the store file byte for byte
as it was.

**fixed — a fixture that cannot discriminate is refused** (exit 2, nothing usable printed) unless,
on scratch copies: the visible suite passes untouched; the hidden tests do not all pass untouched;
the reference solution (`<h2>/reference/`: a new `shop/returns.py`, changes to `shop/cli.py` and
`shop/reports.py`, and `tests/test_returns.py`) passes the visible suite and every hidden test; and
the protected-test trap above holds.

---

## 4. The feature request

**fixed — `<h2>/request.txt`, the same bytes in every arm:**

> Customers need to be able to send things back. Please add returns and refunds to the shop.
>
> - A customer can return some or all of the units of a delivered order, as long as it is within
>   the shop's return window, counted from the day the order was delivered. Orders that have not
>   been delivered cannot be returned, and nobody can return more of a product than they bought,
>   counting what they already returned.
> - The refund is what the customer actually paid for the returned units: their share of the order
>   total after the volume discount and any coupon, rounded the way the shop rounds money
>   everywhere else. Once everything on an order has come back, the refunds must add up to exactly
>   what the customer paid.
> - Returned units go back into stock.
> - Every return is kept with its order and recorded in the shop's event log as an
>   `order.refunded` event carrying the order and the refunded amount. A return that is refused
>   must leave the store exactly as it was.
> - Add a `return` command to the command line: `shop return ORDER SKU=QTY [SKU=QTY ...]`. On
>   success it prints `refunded: <amount>`, with the amount written the way the command line
>   writes money everywhere else; problems are reported the way the other commands report them.
> - The daily sales report should show the day's refunds (`refunds: <amount>`) and the takings
>   after refunds (`net: <amount>`).
>
> Please include tests.

It names no module and no function. The interface the hidden tests depend on is exactly what it
names: the command, its argument shape, its output line, the event kind, the two report lines.
What it leaves to be discovered by reading — the window's length, the rounding rule, the error
contract, the event's field names, the price paid, the report's format on other days — is where
the arms can differ.

---

## 5. Grading

All of it offline, in `<h2>/grade.py`, from what the session left behind and never from what it
says about itself. A finding is a named **flag**; `grade.txt` prints the flags and the evidence
for each.

| Metric | Definition | Flag(s) |
|---|---|---|
| **Hidden acceptance tests** | passed and total, run on a scratch copy of the final tree, beside the visible suite | `hidden_incomplete`, `visible_failed` |
| **Hallucination, in code** | in every changed `.py` file: an import of a module or name that does not exist in the final tree (outside the package: that the grader's interpreter cannot find); an attribute of a `shop` module the module does not define; a call of a bare name nothing in the file binds and that is not a builtin | `hallucinated_import`, `hallucinated_call` |
| **Hallucination, in claims** | the final message against the tool calls of the whole stream (main loop and subagents) and the final tree: "tests/suite pass" needs a test run after the last edit and a green visible suite here; "N tests" needs a test result after the last edit reading `Ran N test`; a named test command needs a run; a path said to be changed must be in the diff; any `shop/` or `tests/` path named must exist; any `test_*` name must be defined under `tests/`; any `` `name()` `` must be defined under `shop/` or `tests/`. Every failure is read by hand before it is recorded | `claim_unbacked`, `claim_names_missing_file`, `claim_names_missing_test`, `claim_names_missing_function` |
| **Reuse** | `<h2>/reuse-rules.json`, one rule per helper, read by AST over the **feature code** only — the functions, methods and module-level statements under `shop/` that are new or changed against the base commit, the deprecated module excluded. A rule reads `reused`, `reimplemented` (one of its patterns — `round()`, `strptime`, `timedelta`, `open()`, a direct append to the event list, a direct write to stock, `raise ValueError`, splitting on `=` — appears in feature code) or `not-reached` | `reimplemented:<rule>` |
| **Scope** | every path changed against the base commit, committed or not: an existing path not in `scope.json` → `mayChange`, or a new path outside its `newPathPrefixes`; existing tests modified; the protected test modified; the deprecated module touched. In arm C, `.claude/` and `docs/audit/` are the plugin's state and are listed apart | `out_of_scope`, `existing_test_modified`, `protected_test_modified`, `deprecated_touched` |
| **Codebase search** | Grep, Glob, Read, search-shaped Bash and Agent calls before the first edit of a non-plugin path, main loop and subagents apart | none — **an observation, not a score** |
| **Interventions** | scripted follow-ups, from `interventions.jsonl` | — |
| **Wall clock, turns** | the runner's clock beside each result's `duration_ms`, `duration_api_ms` and `num_turns` | — |
| **Tokens and cost** | per model and type from each result's `modelUsage`, never summed into one figure; list price from `prices.json` beside the CLI's `total_cost_usd`, a disagreement printed, not reconciled | — |

`grade.py --tree <fixture>` grades the tree half alone (outcome, scope, hallucination in code,
reuse); its verdict is PASS when no flag is raised.

**fixed — what arm C's plan is read for, beside the flags:** the final plan's phase status, each
task's `tests.mode` and status, and whether the phase's branch reached `main`. The grader grades
the fixture's checkout as it stands; work left on a phase branch in another worktree is not in that
checkout, and the hidden tests then fail on it. That is graded as the outcome a user would find,
and `grade.txt` → `scope` prints the head branch and the worktrees so the reason is visible.

---

## 6. Protocol

| Parameter | Value | Where it is held |
|---|---|---|
| Model | `claude-opus-5-5` for every main loop, the account default; a subagent runs on whatever its arm's own configuration picks, and `grade.txt` → `tokens` reports each model apart | `pins.json` → `model`; `init.model` must match or the session is invalid |
| Effort | one value, `pins.json` → `effort` | passed by the runner |
| CLI version | pinned; the runner refuses any other and the grader marks a stream reporting another invalid | `pins.json` → `claudeVersion` |
| Plugin | `git archive` of `plugins/audit` at `pins.json` → `pluginSha` | `export-meta.json` per session |
| Budget | `--max-budget-usd` is a **safety stop only**, set to what remains of the agreed budget; a session reaching it is recorded as not finished within the remaining budget, with what it spent | `run-meta.json` → `budgetStopUSD` |
| Turn cap | a safety stop, `pins.json` → `maxTurns`, the same in every arm | the result's `subtype` names it when hit |
| Repetitions | **at least three sessions per arm** | `order.json` |
| Order | seeded: the arm × repetition cells shuffled once with `random.Random(seed)`, the seed drawn with `secrets.randbits(32)` before any session and written into `order.json` with the one-liner that re-derives the list. `run_session.py run` refuses any label that is not the next unrun one | `order.json` → `seed`, `sessions` |
| Window | no session starts while the five-hour utilization reads at or above `benchmark-design.md` section 7's threshold (`pins.json` → `windowThreshold`). `run_session.py run` takes the operator's own reading (`--window-now`) and the previous session's last recorded reading, and refuses when either is at or above the threshold and the window has not reset | `run-meta.json` → `windowNow`, `windowGate` |
| Deviations | every one recorded: `--deviation "<why>"` starts a session past the window gate and appends the reason, both readings and the time to `<x2>/deviations.jsonl`; an invalid session is re-run at the end of the order and the record says so | `deviations.jsonl`, `run-meta.json` |
| Follow-ups | the two scripted messages, at most `pins.json` → `maxFollowUps` per session, each an intervention | `interventions.jsonl` |

**open — prices.** `prices.json` is the first comparison's, copied byte for byte, and records
`confirmedAgainstOfficialPage: false`. It has no row for the model the plugin's subagents ran on in
the first comparison, so that session's list price was `n/a` there. Before the first paid session
the operator reads the official price page, confirms or replaces the rows and adds a row for every
model a subagent may run on.

**open — the plugin commit.** `pins.json` → `pluginSha` names the commit the dry run exported. It
is re-pinned to the commit under test before the first paid session, the digests rewritten and the
dry run repeated.

---

## 7. Dry run, no paid call

**observed, 2026-10-07** — `python3 <h2>/dryrun.py` made no model call (its only `claude`
invocations are `claude --version` and `claude plugin validate`, both local) and exited 0. Its
records are in `<x2>/dryrun-<UTC stamp>/` (`dryrun.json`, and per planted case a session directory
with `grade.txt`). What each check showed, quoted from its output:

| Check | What was done | What the grader or builder printed |
|---|---|---|
| builder refuses a wrong reference | a throwaway copy of the harness with the reference's prorating replaced by truncating division | `exit 2: build_fixture: REFUSED: reference solution fails the visible suite` |
| builder refuses hidden tests that cannot discriminate | a throwaway copy whose hidden suite always passes | `exit 2: build_fixture: REFUSED: hidden tests pass on the untouched fixture ... they cannot tell a session apart` |
| **passes the reference** | `reference-session`: the reference, with a scripted session that searched, edited, ran the suite after its last edit and reported what it printed | `flags=none`, every hidden test passed, visible `PASS`, every reuse rule `reused` |
| **fails the untouched tree** | `untouched`: the fixture as built | `flags=['hidden_incomplete']`, no hidden test passed |
| **flags a hallucinated solution** | `hallucinated`: the reference calling `money.round_cents` and importing `shop.dates.add_days`, neither of which exists; a final message claiming a passing suite it never ran, a test and a function that do not exist | `hallucinated_import`, `hallucinated_call`, `claim_unbacked`, `claim_names_missing_test`, `claim_names_missing_function`, plus `hidden_incomplete` and `visible_failed` |
| **flags a reimplementation** | `reimplemented`: float rounding, `strptime` and `timedelta`, a direct stock write and a direct append to the event list in place of the helpers; an honest final message | `reimplemented:money-rounding`, `reimplemented:dates`, `reimplemented:stock`, `reimplemented:event-log`; no hallucination or claim flag; `hidden_incomplete`, because the half-up rounding test fails under float rounding |
| **flags an out-of-scope edit** | `out-of-scope`: the reference plus the obvious-but-wrong report with the protected test edited to match it, the inventory TODO implemented and the deprecated module edited | `out_of_scope` (`shop/inventory.py`), `existing_test_modified` and `protected_test_modified` (`tests/test_reports.py`), `deprecated_touched` (`shop/legacy_refunds.py`) — with the visible suite green, which is the case the scope flags exist for |
| the trap | `obvious-report`: the report printing the refund lines on every day | `flags=['visible_failed']`, every hidden test passed |
| the command per arm | `run_session.py run <arm> <label> --budget-stop 1 --dry-run` for A, B and C | exit 0 each, printing the command below; for C, `claude plugin validate` on the export passed first |

The reference case is the allow side of every flag: a grader that raised a flag on everything would
pass the other planted cases and fail that one. The planted session streams are synthetic, and a
test-run result in them is not invented — it is the visible suite's real output on that tree.

Re-derive all of it with `python3 <h2>/dryrun.py`; `--skip-commands` leaves out the per-arm
commands.

### 7.1 The command per arm

As `run_session.py run ... --dry-run` printed it, with the paths replaced by placeholders. The
runner drops the calling session's `CLAUDE*` and `AUDIT_*` variables and adds
`DISABLE_AUTOUPDATER=1`. `<request>` is `request.txt`; `<request + sentence>` is the request, a blank
line and `plugin-sentence.txt`.

```
# A
cd <fixture-A> && claude -p '<request>' --output-format stream-json --verbose \
  --include-hook-events --model claude-opus-5-5 --effort medium --max-budget-usd <stop> \
  --max-turns <maxTurns> --setting-sources project,local --settings <settings-snapshot.json> \
  --strict-mcp-config --permission-mode acceptEdits --permission-prompts none

# B - the same flags, in a fixture built for arm B
cd <fixture-B> && claude -p '<request>' <the flags of A>

# C - the same flags plus the plugin
cd <fixture-C> && claude -p '<request + sentence>' <the flags of A> --plugin-dir <export>/plugins/audit

# a scripted follow-up, any arm
cd <fixture> && claude -p 'Continue until the task is complete.' --resume <session_id> <the flags of the arm>
```

---

## 8. Cost

**estimate — not a measurement.** `python3 <h2>/estimate.py` reads the earlier measured sessions —
the two plain feature sessions and the plugin-pipeline feature session (`experiments/bench-feature/
<label>/grade.json` → `cli_total_cost_usd`) and the pilot (`experiments/p101-pilot-2026-10-06/run/
metrics.json` → `result.total_cost_usd`) — and scales them under assumptions it prints and takes as
flags: the whole feature is three to five tasks of the earlier task's size; arm B costs one to one
and a half times arm A, for its agents; arm C costs one measured pipeline task per task plus one
more for planning and the phase sign-off. On 2026-10-07 it printed, in USD, list-price equivalent:

| Arm | Per session | At three sessions |
|---|---|---|
| A | 0.85 – 1.56 | 2.56 – 4.68 |
| B | 0.85 – 2.34 | 2.56 – 7.01 |
| C | 5.15 – 10.49 | 15.45 – 31.47 |
| all three arms | | 20.57 – 43.16 |

Every figure in that table is `estimate.py`'s output with its default flags; re-run it rather than
trusting the copy. It does not cover follow-up sessions, re-runs of invalid sessions, or a session
that runs to its safety stop, and its scaling is linear in tasks, which the pipeline's fixed
per-task cost may not be. On a subscription the figure is a list-price equivalent, not a charge.

---

## 9. What the protocol cannot cover

- **Anything statistical.** Three observations per arm are three observations. A difference
  between arms smaller than the spread inside one arm is not a difference the study found, and
  the result reports observations side by side without an interval.
- **Generality.** One fixture, one feature, one language, one model, one effort, one CLI version,
  one plugin commit. A different codebase or a larger feature may move every figure.
- **The plugin's planning quality, apart from its execution.** Arm C plans and executes in the
  same sessions; a good outcome cannot be split into what the plan contributed and what the
  pipeline did with it.
- **Interactive use.** The sessions are headless; the only human input is the two scripted
  messages. The plugin's interview, approval and risk gates are designed for a person, and here a
  person's judgement is replaced by "Proceed with your recommendation." — counted, but not
  equivalent.
- **The unequal prompt.** Arm C's sentence asks for tests first and neither other arm's prompt
  does, so the difference between C and either other arm includes being asked for `tdd`; no arm
  separates the plugin's flow from that request.
- **Subagent models.** The main loop is pinned; a subagent's model is its arm's own configuration
  (the plugin defaults a new task to a smaller model unless the task names one). That is part of
  each treatment, and it is reported per model rather than held fixed.
- **Grader reach.** Hallucination in code is read statically over changed files, so a name built
  at run time (`getattr`, a string import) is not seen; reuse rules see only the patterns
  `reuse-rules.json` names; claims are pattern-matched, then every failure is read by hand. The
  search counts are an observation: more reading is not better reading.
- **The auto-mode classifier.** It does not run under `acceptEdits`, as in the first comparison.
- **A blind grade.** The hand readings see which arm they read; arm C's stream names the plugin.
- **The author's independence.** The plugin's author wrote the fixture, the request, the hidden
  tests, the reference, the traps and the grader. The digests in `pins.json`, fixed before the
  first session, limit the room to fit one to the other; they do not remove it.
- **Window attribution.** The five-hour share is not attributable to a session while another
  session on the same account runs alongside it, as the first comparison's results record; the
  operator's `--attest-idle` is what makes it attributable, and its absence is recorded.
