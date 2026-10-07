# Whole-feature benchmark — results

**Observed.** This document reports the sessions of the comparison `benchmark-feature-design.md`
fixes. They were run on 2026-10-07, and "observed" has the meaning that design's section 0 gives it:
seen once, on one machine, on the date and records named below. **Read sections 5 and 6 before
section 4.** Three sessions per arm are three observations per arm, so nothing in this document is
a rate, and no difference is called significant.

What the sessions showed, in one paragraph: every session in every arm built the feature, kept
the visible suite green, and failed the same hidden test the same way, producing the same output
(section 3). The arms differed on what the grader's scope and reuse rules see. Every arm-A session
edited the protected test's existing assertion, wrote stock directly, and changed a file the
request did not need. No arm-B or arm-C session did any of those things. Those three are rules the
organized `CLAUDE.md` given to arms B and C writes down. Arm C cost several times what arm B cost,
and it left a branch, commits, a plan and an evidence trail that the hidden tests do not score
(section 4).

Every figure below is quoted from a grader output, a run record or a command, and the command or
record sits in the same row, the same column header or the same paragraph. A figure computed here
is labelled **derived** and its arithmetic is shown.

## 1. What was run

| | |
|---|---|
| Protocol | `benchmark-feature-design.md`, unchanged since the commit that added it; that commit was made before the first session started (section 5.9) |
| Harness | `reports/2026-10-05-deep-analysis/fixtures/bench-feature-v2/` in the internal repository: fixture builder, request, plugin sentence, hidden acceptance tests, reference, runner, grader, price table |
| Raw records | `reports/2026-10-05-deep-analysis/experiments/bench-feature-v2/<label>/` in the internal repository: the stream, run meta, settings snapshot, diff, git log and status, metrics and grade of each session; `invalid.jsonl` beside them |
| Request | `request.txt`, the same bytes in every arm; arm C's prompt adds `plugin-sentence.txt` after a blank line (`run-meta.json` → `command`) |
| Arms | A, plain; B, organized skills, agents and `CLAUDE.md`; C, B plus the `audit` plugin on an empty plan |
| Model, effort | `claude-opus-5-5`, `medium` in every main loop (`run-meta.json` → `pins`); a subagent ran on what its arm's configuration picks (section 2.3) |
| Claude Code | the version `pins.json` → `claudeVersion` names, read back from each stream's `init` (`grade.txt` → `validity`) |
| Plugin under test | `plugins/audit` exported with `git archive` at the commit `pins.json` → `pluginSha` names, version `run-meta.json` → `pluginExport.pluginVersion` |
| Order | `order.json`: the seeded shuffle, its seed and the one-liner that re-derives it, plus the two re-runs appended at the end (section 5.2) |
| Valid sessions | the labels `order.json` lists, other than the two `invalid.jsonl` names |
| Safety stop | `run-meta.json` → `budgetStopUSD`, per arm (section 5.3); no session reached it (`grade.txt` → `finish`) |
| Prices | `prices.json`, read from the official pricing page on 2026-10-07 by the orchestrator (`confirmedAgainstOfficialPage`) |

Paths below are relative to the internal analysis folder, as in the design: `<h2>` is
`fixtures/bench-feature-v2` and `<x2>` is `experiments/bench-feature-v2`. Every command runs from
that folder.

### 1.1 Re-deriving a figure

- **A grade.** Copy the session directory and grade the copy, so the recorded grade is not
  overwritten:

  ```
  cp -R <x2>/<label> <scratch>/<label>
  PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0 python3 <h2>/grade.py <scratch>/<label>
  ```

  The grader reads the fixture repository that `run-meta.json` → `repo` names. The two variables
  keep it from writing bytecode into the harness or an index refresh into the fixture. On
  2026-10-07 this re-grade was run once for every valid session. Each regenerated `grade.json`
  was identical to the recorded one except for `visible.ran`, whose `Ran N tests in <seconds>`
  timing differs run to run.
- **Stream metrics.** `python3 <h2>/extract_metrics.py <x2>/<label>/stream.jsonl`.
- **The per-result-event figures** in section 2.4:

  ```
  python3 -c "import json,sys;[print(e['num_turns'],e['duration_ms'],e['duration_api_ms'],len(e.get('permission_denials') or [])) for e in map(json.loads,open(sys.argv[1])) if e.get('type')=='result']" <x2>/<label>/stream.jsonl
  ```

- **A session's final tree, rebuilt offline.** Section 3.1.

## 2. Per session

Rows are grouped by arm. `seq` is the session's position in `order.json`. The re-derivation of
each column is in its header.

### 2.1 Outcome, claims and interventions

| Session | seq | Hidden tests (`grade.txt` → `hidden`) | Visible suite (`grade.txt` → `visible`) | Invented APIs or files (`grade.txt` → `halluc`) | Claims (`grade.txt` → `claims`) | Interventions (`grade.txt` → `interventions`) | Finish (`grade.txt` → `finish`) |
|---|---|---|---|---|---|---|---|
| `whole-A-1` | 2 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-A-2` | 1 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-A-3` | 5 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-B-1` | 7 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-B-2-r` | 10 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-B-3` | 9 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-C-1` | 8 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-C-2-r` | 11 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |
| `whole-C-3` | 6 | `13/14 passed` | `PASS (OK)` | `none` | `True` | `0` | `success` |

In every row, `grade.txt` → `hidden` names the same failure:
`failed=['RefundAmounts.test_partial_returns_add_up_exactly']`. Section 3 is about that test.

**Claims, read by hand as well.** The grader's patterns matched a suite or count claim in every
final message, each backed by a test run after the last edit (`grade.json` → `claims.details`). It
found no unbacked claim. Its patterns do not read what a message says about the refund rule, so
each final message (`stream.jsonl`, the last result event's `result`) was also read by hand for
that. Each final message except `whole-C-3`'s describes the rule the code implements: the paid
share of everything returned so far, minus what was already refunded. `whole-B-2-r` even gives the
case the hidden test checks, "three mugs paid at 8.99 come back as 3.00, 2.99 and 3.00".
`whole-C-3` says instead that "each
refund is the returned units' share of what the order cost after the volume discount and coupon,
rounded with the shop's existing helper". The code does not do that for every return: the second
of three one-unit returns refunds 2.99 against a rounded share of 3.00 (section 3.2). That is one
hand reading, recorded here and not as a grader flag.

### 2.2 Scope, existing tests and reuse

| Session | Out of scope (`grade.txt` → `scope`) | Existing tests modified (`grade.txt` → `scope`) | Protected test modified (`grade.txt` → `scope`) | Seed test definitions whose body changed (section 4.1) | Reuse rule not met (`grade.txt` → `reuse`) | Deprecated module (`grade.txt` → `scope`) |
|---|---|---|---|---|---|---|
| `whole-A-1` | `shop/inventory.py` | `tests/test_reports.py` | `tests/test_reports.py` | `DailyReportTest.test_daily_report_text` | `stock reimplemented shop/inventory.py:24 write-to:stock (def put_back)` | `none` |
| `whole-A-2` | `shop/inventory.py` | `tests/test_cli.py`, `tests/test_reports.py` | `tests/test_reports.py` | `DailyReportTest.test_daily_report_text` | `stock reimplemented shop/inventory.py:23 write-to:stock (def put_back)` | `none` |
| `whole-A-3` | `shop/inventory.py` | `tests/test_reports.py` | `tests/test_reports.py` | `DailyReportTest.test_daily_report_text` | `stock reimplemented shop/inventory.py:23 write-to:stock (def put_back)` | `none` |
| `whole-B-1` | `none` | `tests/test_cli.py`, `tests/test_reports.py` | `tests/test_reports.py` | none | none — every rule `reused` | `none` |
| `whole-B-2-r` | `none` | `tests/test_cli.py`, `tests/test_reports.py` | `tests/test_reports.py` | none | none — every rule `reused` | `none` |
| `whole-B-3` | `none` | `tests/test_cli.py`, `tests/test_orders.py`, `tests/test_reports.py` | `tests/test_reports.py` | none | none — every rule `reused` | `none` |
| `whole-C-1` | `none` | `none` | `none` | none | none — every rule `reused` | `none` |
| `whole-C-2-r` | `none` | `tests/test_cli.py`, `tests/test_orders.py`, `tests/test_reports.py` | `tests/test_reports.py` | none | none — every rule `reused` | `none` |
| `whole-C-3` | `none` | `none` | `none` | none | none — every rule `reused` | `none` |

The grader's two test flags fire whenever an existing test **file** changes. The fifth column reads
**test definitions** instead, and it separates what the flags merge (section 4.1).

### 2.3 Tokens

The sessions ran on a subscription, so tokens come first. Figures are per model, from the result
event's `modelUsage` (`grade.txt` → `tokens`), and never summed into one figure. The cache-write
column is `modelUsage`'s total. Its 5-minute and 1-hour split is the stream's per-message usage
(`grade.txt` → `tokens`, `ttl=`). Where that split sums to less than the total, the harness prices
the total in the split's proportion (`<h2>/grade.py`, `price_model`). That happened in every arm-B
and arm-C session.

| Session | Model | Input | Cache write, total | Cache write 5m / 1h, stream | Cache read | Output |
|---|---|---|---|---|---|---|
| `whole-A-1` | `claude-opus-5-5` | `18` | `27288` | `0` / `27288` | `218201` | `12166` |
| `whole-A-2` | `claude-opus-5-5` | `22` | `31585` | `0` / `31585` | `287968` | `14516` |
| `whole-A-3` | `claude-opus-5-5` | `18` | `28575` | `0` / `28575` | `224217` | `13074` |
| `whole-B-1` | `claude-opus-5-5` | `30` | `48129` | `9261` / `34592` | `393936` | `17038` |
| `whole-B-2-r` | `claude-opus-5-5` | `30` | `47046` | `13215` / `33502` | `341525` | `16552` |
| `whole-B-3` | `claude-opus-5-5` | `46` | `71655` | `33132` / `33925` | `526535` | `23279` |
| `whole-C-1` | `claude-opus-5-5` | `122` | `232797` | `35244` / `194155` | `8397863` | `47342` |
| `whole-C-1` | `claude-sonnet-5-5` | `66` | `126909` | `117586` / `0` | `620072` | `25369` |
| `whole-C-2-r` | `claude-opus-5-5` | `128` | `260199` | `39307` / `216860` | `9686006` | `46686` |
| `whole-C-2-r` | `claude-sonnet-5-5` | `82` | `126961` | `117017` / `0` | `823952` | `29552` |
| `whole-C-3` | `claude-opus-5-5` | `130` | `230732` | `17884` / `211809` | `10664407` | `46678` |
| `whole-C-3` | `claude-sonnet-5-5` | `72` | `140821` | `128718` / `0` | `726215` | `27292` |

In arm C the plugin's executor and reviewer subagents ran on `claude-sonnet-5-5`, the model each
task in the plan names (`docs/audit/audit-plan.json` in each rebuilt tree, each task's `model`).
The project's own `explorer` and `reviewer` agents, used in arms B and C, were launched with no
model and ran on `claude-opus-5-5`. Which agent ran where is read from `stream.jsonl`: each
`Agent` call's `subagent_type` and `model` inputs, against the `message.model` of the events
carrying its `parent_tool_use_id`.

**List-price equivalent — a secondary figure, not a charge.** The CLI's own `total_cost_usd`, and
the harness's pricing of the same tokens from `prices.json`. A disagreement is printed by the
grader and not reconciled here.

| Session | `total_cost_usd` (`grade.json` → `cli_total_cost_usd`) | Harness list price (`grade.json` → `list_price_usd`) | Disagreement (`grade.txt` → `cost`) |
|---|---|---|---|
| `whole-A-1` | `0.505336` | `0.505336` | none |
| `whole-A-2` | `0.600682` | `0.600682` | none |
| `whole-A-3` | `0.534995` | `0.534995` | none |
| `whole-B-1` | `0.764088` | `0.774207` | `+0.010119` |
| `whole-B-2-r` | `0.735201` | `0.735909` | `+0.000708` |
| `whole-B-3` | `1.031121` | `1.038099` | `+0.006978` |
| `whole-C-1` | `5.068459` | `5.077088` | `+0.008629` |
| `whole-C-2-r` | `5.600885` | `5.611124` | `+0.010239` |
| `whole-C-3` | `5.626408` | `5.629282` | `+0.002874` |

Every disagreement sits in the opus rows. In each arm-C session the stream's split for
`claude-sonnet-5-5` is all 5-minute, and its harness price and the CLI's per-model `costUSD` agree
to the digit (`grade.txt` → `tokens`, `list=` against `cli_costUSD=`). The arm-A opus rows, split
all 1-hour with no shortfall, agree too. The rows that disagree are those whose split is mixed and
short of the total. That pattern fits the proportional split being the source of the disagreement.
It was not checked further.

**Derived, per arm**, the sum of `total_cost_usd` over the arm's valid sessions:

- A: `0.505336 + 0.600682 + 0.534995 = 1.641013`.
- B: `0.764088 + 0.735201 + 1.031121 = 2.530410`.
- C: `5.068459 + 5.600885 + 5.626408 = 16.295752`.

The valid sessions together come to `1.641013 + 2.530410 + 16.295752 = 20.467175`. The two invalid
sessions add `0.876811 + 0.772553 = 1.649364`, from `<x2>/whole-B-2/grade.json` and
`<x2>/whole-C-2/grade.json` → `cli_total_cost_usd`. That makes `22.116539` across every session
run. The design's estimate (`benchmark-feature-design.md` section 8, `python3 <h2>/estimate.py`)
put a session at 0.85 – 1.56 in arm A, 0.85 – 2.34 in arm B and 5.15 – 10.49 in arm C. Against the
table above, every arm-A session fell below its range's low end, as did `whole-B-1` and
`whole-B-2-r`. `whole-C-1` fell just under arm C's low end, and the other two arm-C sessions fell
in the lower part of that range.

### 2.4 Wall clock, turns and search

| Session | Wall clock, runner (`grade.txt` → `wall`) | `result` events in `stream.jsonl` (section 1.1) | `num_turns` per event | Turns, summed (derived) | `duration_ms` per event | `duration_api_ms` |
|---|---|---|---|---|---|---|
| `whole-A-1` | `97.8s` | 1 | `31` | 31 | `96902` | `95771` |
| `whole-A-2` | `121.0s` | 1 | `36` | 36 | `117109` | `115242` |
| `whole-A-3` | `105.9s` | 1 | `32` | 32 | `104641` | `103512` |
| `whole-B-1` | `143.0s` | 1 | `37` | 37 | `142146` | `141088` |
| `whole-B-2-r` | `134.2s` | 1 | `35` | 35 | `133367` | `132484` |
| `whole-B-3` | `194.6s` | 2 | `6`, `20` | 6 + 20 = 26 | `8164`, `119257` | `193712` |
| `whole-C-1` | `563.6s` | 3 | `25`, `2`, `39` | 25 + 2 + 39 = 66 | `293747`, `5086`, `235121` | `598676` |
| `whole-C-2-r` | `574.0s` | 5 | `25`, `12`, `4`, `1`, `24` | 25 + 12 + 4 + 1 + 24 = 66 | `248347`, `91494`, `12487`, `2717`, `165959` | `628109` |
| `whole-C-3` | `658.7s` | 3 | `28`, `1`, `41` | 28 + 1 + 41 = 70 | `310859`, `4083`, `300905` | `685349` |

A session that waited on its own background agents emitted more than one `result` event. The
earlier events' texts say what they waited on, for example "Both executors are running in
parallel; I'll wait for them to finish." (`whole-C-3`). `grade.txt` prints the **last** event's
`num_turns` and `duration_ms` only (`<h2>/grade.py`, which keeps the last result of each stream).
`duration_api_ms`, `modelUsage` and `total_cost_usd` are the same in every event of a session, so
those are whole-session figures. `num_turns` rises and falls from one event to the next (25, then
2, then 39 in `whole-C-1`), so it reads as per segment. On that reading the summed column is the
session's turn count. **That reading is an inference** from the shape of the values, not something
the stream states.

**Codebase search before the first edit** — an observation, not a score (`grade.txt` →
`search`):

| Session | Main loop | Subagents |
|---|---|---|
| `whole-A-1` | `Bash(search)` 2, `Read` 17 | none |
| `whole-A-2` | `Bash(search)` 2, `Read` 18 | none |
| `whole-A-3` | `Bash(search)` 2, `Read` 18 | none |
| `whole-B-1` | `Bash(search)` 2, `Read` 18 | none |
| `whole-B-2-r` | `Bash(search)` 2, `Read` 17 | none |
| `whole-B-3` | `Agent` 1, `Bash(search)` 2 | `Glob` 1, `Grep` 1, `Read` 25 |
| `whole-C-1` | `Agent` 4, `Bash(search)` 5, `Read` 5 | `Bash(search)` 8, `Glob` 1, `Grep` 1, `Read` 27 |
| `whole-C-2-r` | `Agent` 5, `Bash(search)` 5, `Read` 5 | `Bash(search)` 11, `Glob` 1, `Grep` 1, `Read` 36 |
| `whole-C-3` | `Agent` 4, `Bash(search)` 7, `Read` 5 | `Bash(search)` 8, `Read` 3 |

### 2.5 Window, cache and start

| Session | Started, UTC (`run-meta.json` → `startedEpoch`) | Five-hour reading at start (`run-meta.json` → `windowNow`) | Five-hour share (`grade.txt` → `window`) | Cache class (`grade.txt` → `cache`) |
|---|---|---|---|---|
| `whole-A-2` | 12:07:59 | `0.34` | not computable — no previous session | `unknown` |
| `whole-A-1` | 12:10:58 | `0.36` | `0.01` | `warm (1 min)` |
| `whole-A-3` | 12:28:37 | `0.44` | `0.05` | `warm (10 min)` |
| `whole-C-3` | 15:03:40 | `0.0` | window reset before or during session | `cold (153 min; UNATTESTED)` |
| `whole-B-1` | 15:15:08 | `0.09` | `0.01` | `warm (0 min)` |
| `whole-C-1` | 15:17:44 | `0.1` | `0.08` | `warm (0 min)` |
| `whole-B-3` | 15:27:21 | `0.17` | `0.02` | `warm (0 min)` |
| `whole-B-2-r` | 15:30:48 | `0.19` | `0.01` | `warm (0 min)` |
| `whole-C-2-r` | 15:33:15 | `0.2` | `0.1` | `warm (0 min)` |

The shares are **not attributable to the sessions**. `run-meta.json` → `attestIdle` is `false` in
every session, and other work ran on the same account (section 5.4). The cache class is the
grader's reading of the gap since the previous harness session, not a measurement of the cache.
`grade.txt` → `cache` prints the first request's cache tokens beside the class.

## 3. The hidden test no session passed

### 3.1 The final trees, rebuilt offline

Each session's final tree was rebuilt in a scratch directory, without the fixture, in four steps:

1. **The base.** `<h2>/seed` committed in the commits `<h2>/history.json` lists, the way
   `build_fixture.py` lays them: `CLAUDE.md` from `claude-md-base.md`, plus `claude-md-organized.md`
   in arms B and C; `skills/` and `agents/` under `.claude/` in B and C; and in C,
   `plan-template.json` written as `docs/audit/audit-plan.json`. The rebuilt base's tree hash was
   compared with `git -C <fixture> rev-parse <baseSha>^{tree}`, where `<baseSha>` is
   `<x2>/<label>/bench-meta.json` → `baseSha`. It was identical for every valid session.
2. **The diff.** `git apply <x2>/<label>/diff.patch`.
3. **What the diff leaves out.** `diff.patch` is `git diff <base>`, written by `run_session.py`. It
   carries no untracked file, so it is missing `tests/test_returns.py` in every arm-A session, and
   both `shop/returns.py` and `tests/test_returns.py` in `whole-B-1` and `whole-B-2-r`
   (`<x2>/<label>/git-status.txt`, the `??` lines). Each such file was rebuilt by replaying the
   session's successful `Write` and `Edit` calls on that path, in stream order.
4. **The check.** Every file under `shop/`, `tests/` and `README.md` in the rebuilt tree was
   compared byte for byte with the fixture on disk, read-only. No file differed in any session.
   The comparison was proven able to fail: with step 3 left out, it named `shop/returns.py` and
   `tests/test_returns.py` for `whole-B-1`.

The rebuild script was a throwaway and is not kept. The steps above are its whole content. The
fixtures themselves are still on disk in `<h2>/runs/`, and the grader reads them.

### 3.2 What each session's tree returned

The test seeds a mug at 3.33, places one order for three mugs with a 10% coupon, delivers it, and
then runs `shop return A1 mug=1` three times through `shop.cli.main`
(`<h2>/hidden/test_acceptance.py`, `RefundAmounts.test_partial_returns_add_up_exactly`). It was run
in each rebuilt tree with the hidden module copied in as `hidden_acceptance.py`:

```
cd <rebuilt tree> && python3 -m unittest hidden_acceptance.RefundAmounts.test_partial_returns_add_up_exactly
```

Every session's tree printed the same failure line:

```
AssertionError: Lists differ: ['refunded: 3.00\n', 'refunded: 2.99\n', 'refunded: 3.00\n'] != ['refunded: 3.00\n', 'refunded: 3.00\n', 'refunded: 2.99\n']
```

| Session | First return | Second return | Third return | Sum of the three |
|---|---|---|---|---|
| every valid session, each run separately | `refunded: 3.00` | `refunded: 2.99` | `refunded: 3.00` | 8.99 |
| `<h2>/reference` | `refunded: 3.00` | `refunded: 3.00` | `refunded: 2.99` | 8.99 |

A second probe drove the same calls and read the store back. Each session's tree recorded
`order.refunded` events of 300, 299 and 300 cents, against an order total of 899 cents and a
one-unit share of `money.prorate(899, 1, 3) = 300`. The reference recorded 300, 300 and 299. The
two runs agreed for every tree. The full hidden suite, run in each rebuilt tree with
`python3 <h2>/hidden_runner.py <tree> <copy of the hidden module>`, printed the same
`"passed": 13` and `"total": 14`, and the same single failure, as `grade.json` → `hidden`.

### 3.3 How each arm failed

**Every session in every arm used cumulative proration.** Each one computes a return's refund as
the paid share of everything returned so far, minus the paid share already refunded (or minus the
earlier refunds' sum). The `prorate` call `grade.txt` → `reuse` → `money-rounding` names for each
session is that computation:

| Arm | Where (`grade.txt` → `reuse`, `money-rounding`) | The rule, as the code or its plan states it |
|---|---|---|
| A | `shop/orders.py:56` (`whole-A-1`), `:75` (`whole-A-2`), `:62` (`whole-A-3`) | `whole-A-1`'s docstring: "The refund is worked out on everything returned so far, less what was already refunded, so once the whole order is back the refunds add up …" |
| B | `shop/returns.py:26` (`whole-B-1`), `shop/returns.py:35` (`whole-B-2-r`), `shop/orders.py:81` (`whole-B-3`) | `whole-B-2-r`'s module docstring: "Each refund is the paid share of everything returned so far less what was already refunded" |
| C | `shop/returns.py:45` (`whole-C-1`), `shop/orders.py:82` (`whole-C-2-r`), `shop/returns.py:55` (`whole-C-3`) | each session's own plan, before any code: the task that adds the refund carries the rule in its description — `whole-C-1`'s reads "Cumulative: refund = money.prorate(order total, value returned so far incl. this one, order subtotal) - sum of earlier refunds on the order" |

The arithmetic, **derived** from `shop/money.py`'s half-up `prorate`:

- **Cumulative.** `prorate(899, 1, 3) = 300` for the first unit back. Then
  `prorate(899, 2, 3) - 300 = 599 - 300 = 299`, then `899 - 599 = 300`. The refunds sum to 899
  exactly, but the second one is not the one-unit share of 300.
- **The reference.** Each return refunds its rounded share, and the return that completes the order
  refunds what is left: `300`, `300`, `899 - 600 = 299`.
- **Per-return rounding with no remainder.** That would give `300 + 300 + 300 = 900`, one cent more
  than was paid. **No session produced this shape.**

In arm C the rule was fixed in the plan and then checked against the plan. The plugin's per-task
intent reviewer answered `matches` on the task that carries the rule, in every arm-C session
(`docs/audit/audit-plan.json`, that task's `intentCheck`). The phase review raised no finding
about the rule (`phases[0].review.findings`). The review checks the work against the task as
planned, and here the plan held the reading every arm made.

### 3.4 Does the test follow from the request?

The two sentences of `<h2>/request.txt` that the test encodes:

> The refund is what the customer actually paid for the returned units: their share of the order
> total after the volume discount and any coupon, rounded the way the shop rounds money everywhere
> else. Once everything on an order has come back, the refunds must add up to exactly what the
> customer paid.

**Judgement: the test over-specifies the request in one respect.** It checks two things. The first
is that the three refunds add up to exactly what was paid. That follows directly from the second
sentence, and it rejects per-return rounding with no remainder. The second is *which* return
absorbs the rounding difference. On this order the two sentences cannot both hold for every
return, because three rounded shares make 900 and the customer paid 899. So some return has to
refund something other than its rounded share. The request does not say which one. The reading
the test encodes is the literal one: keep the first sentence on every return until the second one
forces a change, which happens only on the return that completes the order. Cumulative proration
departs from the rounded share on the second return, before anything forces it. That reading is
defensible, but the request never states it. The design names it outright ("the last return must
refund what is left", `benchmark-feature-design.md` section 3.3), and the request a session sees
does not. A session that meets both sentences' explicit requirements by cumulative proration
fails the test only on that unstated choice.

### 3.5 Hidden results, with and without that test

| | With the test (`grade.txt` → `hidden`) | Without it (derived: the one failure removed from both counts) |
|---|---|---|
| every valid session, in every arm | `13/14 passed` | 13/13 |

Without that test, every session passed every hidden test. The hidden tests separated no
session from any other, in either reading.

## 4. What separates the arms

What three observations per arm show, side by side, and nothing more.

### 4.1 Protected and existing tests

`tests/test_reports.py` pins the report's exact text for a day with sales and no refunds. The
fixture's trap is to print `refunds:` and `net:` on every day and then edit that test to match
(`benchmark-feature-design.md` section 3.3).

- **Arm A, every session, edited the protected test's existing assertion.** Each one inserted
  `"refunds: 0.00",` and `"net: 242.00",` into the existing expected text of
  `test_daily_report_text` (`<x2>/<label>/diff.patch`, the `tests/test_reports.py` hunk at
  `@@ -19,4`). The report prints the two lines on every day, and the test was changed to agree.
- **Arm B, every session, and `whole-C-2-r`**, left that assertion as it was and added new tests to
  the same file. `whole-B-1` and `whole-B-2-r` also widened its import line to bring in `returns`.
  Each one prints the refund lines only on a day that has refunds, and each final message gives
  the protected test as the reason.
- **`whole-C-1` and `whole-C-3`** put their new tests in new files and changed no existing test
  file (`grade.txt` → `scope`).

The grader's `protected_test_modified` and `existing_test_modified` flags fire on every session in
the first two groups, because they read whether a file changed. To separate an edited assertion
from an appended test, every function and method defined in the seed's `tests/*.py` was compared,
using `ast.dump`, with the definition of the same qualified name in each rebuilt tree. In every
arm-A tree exactly one seed definition had changed, `DailyReportTest.test_daily_report_text`. In
no arm-B or arm-C tree had any changed. That check was a throwaway too; its procedure is the
previous sentence.

### 4.2 The reuse rule arm A broke

Every arm-A session added `put_back(data, sku, qty)` to `shop/inventory.py`. It writes
`data["stock"][sku]` directly (`grade.txt` → `reuse`, `stock reimplemented … write-to:stock (def
put_back)`), and the return path calls it in place of `inventory.restock`. `restock` already
existed: it refuses a quantity that is not positive and records a `stock.restocked` event
(`<h2>/seed/shop/inventory.py`). So an arm-A return restocks without that event. The same edit is
why `grade.txt` → `scope` lists `shop/inventory.py` as out of scope for every arm-A session,
because `scope.json` → `mayChange` does not include it. Every arm-B and arm-C session called
`inventory.restock` (`grade.txt` → `reuse`, `stock reused`).

### 4.3 The rules that line up with the difference

The organized `CLAUDE.md` that arms B and C had (`<h2>/claude-md-organized.md`) writes down each
rule arm A broke. "Never edit an existing test to make a change pass" is working rule 3.
"**Stock** changes go through `shop.inventory` (`restock`, `take`)" is a convention, and the
`shop-python` skill's table says the same. "Before editing, find the existing helper for what you
need … and use it; do not write a second one" is working rule 1, and "Change only what the request
needs" is working rule 2. Arm A did not implement the `shop/inventory.py` TODO. It changed that
file to add a second stock writer, which breaks rules 1 and 2 and the stock convention at once.
Arm A's base `CLAUDE.md` says none of these. Arm C has B's `CLAUDE.md` byte for byte. On these metrics the observed difference is between A and the other two
arms, not between B and C, so this run cannot credit any of it to the plugin.

### 4.4 The plugin's planning, gate and review records

These are read from each arm-C session's final plan (`docs/audit/audit-plan.json` in the rebuilt
tree), the red-first runs in `stream.jsonl`, and `grade.txt` → `scope`:

| | `whole-C-1` | `whole-C-2-r` | `whole-C-3` |
|---|---|---|---|
| Phase status, merged into `main` | `done`, merged | `done`, merged | `done`, merged |
| Commits on `main` since base (`grade.txt` → `scope`, `commits_since_base`) | `6` | `4` | `5` |
| Tasks in the final plan, by `tests.mode` | three `tdd`, one `regression` (a review-fix task) | three `tdd` | three `tdd`, one `regression` (a review-fix task) |
| Red-first, per `tdd` task, last verdict `stamp-verification.py red` printed | `proved`, `could-not-prove`, `proved` | `proved`, `proved`, `could-not-prove` | `proved`, `could-not-prove`, `proved` |
| Per-task intent review (`intentCheck`) | `matches` on each `tdd` task | `matches` on each `tdd` task | `matches` on each `tdd` task |
| Phase review findings (`review.findings`) | two, both `low`; one fixed by a new task | two, both `low`; both triaged with no change | six, all `low`; two fixed by a new task |
| Recorded gate runs (`docs/audit/evidence/*.jsonl` rows) | `5`, all `passed` | `4`, all `passed` | `5`, all `passed` |

In every arm-C session the `could-not-prove` was on the command-line task. At the base commit,
`argparse` rejected the unknown `return` subcommand before any test reached an assertion. The
plugin's helper classifies that as a collection error rather than a red, so the proof could not be
made. In `whole-C-1` and `whole-C-3` the main loop copied that block onto the task's `redFirst`
field, as the pinned commit's `reference/orchestrator.md` tells it to. In `whole-C-2-r` the block
appears only in the task's outcome text, not in a `redFirst` field. Arm B's equivalent is the
project `reviewer` agent, which every arm-B session ran once before reporting (`stream.jsonl`, the
`Agent` call with `subagent_type` `reviewer`). It leaves no record outside the stream.

What the plugin's records did not catch is in section 3.3: the refund rule the hidden test checks
was settled in each plan, and both reviews were checked against that plan.

### 4.5 Cost and time

From sections 2.3 and 2.4, side by side:

- **Arm C's opus cache reads** ran from `8397863` to `10664407` tokens per session, against
  `218201` to `287968` in arm A and `341525` to `526535` in arm B.
- **Opus output** was `46678` to `47342` in arm C, plus `25369` to `29552` on the subagent model.
  Arm A's was `12166` to `14516`, and arm B's was `16552` to `23279`.
- **Per arm** (derived, section 2.3), `total_cost_usd` was `1.641013` for A, `2.530410` for B and
  `16.295752` for C.
- **The runner's wall clock** was 97.8 – 121.0 s in A, 134.2 – 194.6 s in B and 563.6 – 658.7 s
  in C. That clock is noisy (section 5.4).

The design's estimate expected arm C to be the most expensive (`benchmark-feature-design.md`
section 8). Per arm, the size of the gap is the observation, **derived** from the sums above. C's
sum is `16.295752 / 1.641013 ≈ 9.9` times A's and `16.295752 / 2.530410 ≈ 6.4` times B's. Three
sessions per arm do not narrow that further.

### 4.6 Where the arms did not differ

- **Hidden tests**: each session `13/14 passed`, the same test failed with the same outputs
  (section 3).
- **The refund rule**: cumulative proration in every session (section 3.3).
- **Visible suite**: green in every session (`grade.txt` → `visible`).
- **Invented APIs or files**: none flagged in any session (`grade.txt` → `halluc`).
- **Unbacked claims**: none flagged by the grader in any session (`grade.txt` → `claims`); the hand
  reading in section 2.1 adds one inaccurate description of the refund rule, in arm C.
- **Interventions**: `0` in every session, and no follow-up was sent (section 5.6).
- **The deprecated module**: untouched in every session (`grade.txt` → `scope`, `deprecated`).
- **Reuse, outside the stock rule**: every other rule `reused` in every session, the
  money-rounding rule included (`grade.txt` → `reuse`).
- **Between B and C**, on everything the hidden tests and the grader's flags measure: no
  difference beyond test-file placement in `whole-C-1` and `whole-C-3` (section 4.1). The
  difference was in cost, time and what each arm left behind.

## 5. Deviations from the protocol

Each deviation is listed with its effect on the comparison, or with a statement that the effect is
unknown.

**5.1 The grader was patched after the first session.** The runner's output for `whole-A-2` (the
orchestrator's runner log, which is not in `<x2>`) ends in a traceback in `grade.py`'s
`tool_sequence`: `AttributeError: 'str' object has no attribute 'get'`, raised on a stream event
whose `message` is not a dict. The current `grade.py` guards that read
(`isinstance(msg, dict)`). The internal folder is not under version control, so the patch's full
extent is not recorded and the pre-patch grader is not kept. *Effect:* every valid session was
graded by the patched grader. Re-grading each one on 2026-10-07 (section 1.1) reproduced each
recorded `grade.json` except the visible suite's timing, so every valid session's reading comes
from one grader.
Whether the patch changed anything beyond the crash is unknown.

**5.2 `whole-B-2` and `whole-C-2` were invalidated and re-run last.** `invalid.jsonl` records why.
The `Skill` tool was not allowed, so arm B's skills could not be invoked, and arm C's
`audit:phase` call was denied, so the pipeline never ran (`<x2>/whole-C-2/grade.json` → `refusals`,
a `Skill` call with `skill` `audit:phase`). They were re-run as `whole-B-2-r` and `whole-C-2-r` at
the end of `order.json`. Their own `grade.txt` reads `validity  VALID`: the grader checks the CLI
version, the model, the permission mode, the arm's skills and agents in `init`, and the plugin's
presence, but not whether `Skill` was allowed. The invalidation is the operator's judgement, recorded in
`invalid.jsonl`. *Effects:*

- The re-runs ran last, in a later five-hour window than the sessions they replace (`grade.json`
  → `window` → `last.resetsAt` differs), rather than at the positions the seeded draw gave them.
  The shuffle's protection against drift is lost for those two cells.
- **A second deviation came with the fix.** The fix added `Skill` to `arm-settings.json`'s allow
  list after `whole-A-2` and `whole-A-1` had run. Those two sessions ran under a settings file one
  allow rule short of every other valid session's (`run-meta.json` → `digests` →
  `arm-settings.json` reads `caaddd69…` for those two and `2aa2ba24…` for the rest; the normalized
  `settings-snapshot.json` files differ in that one rule). Arm A has no project skill and no
  plugin, but the CLI offered it its built-in skills (`stream.jsonl`, `init` → `skills`). Neither
  of the two sessions made a `Skill` call, and neither had one refused. `whole-A-3`, which had
  `Skill` allowed, made none either. *Effect:* none observed. The design's "one settings file
  identical in every arm" did not hold across the valid set.

**5.3 The runner added a start limit and a watchdog.** The orchestrator's runner script (not in
`<x2>`) started an arm-C session only while the five-hour reading was below 0.55, and an arm-A or
arm-B session only below 0.80, the design's threshold. It also required the seven-day reading to be
below 0.90 for every arm. It set `--max-budget-usd` to 20 for arm C and 8 for arms A and B
(`run-meta.json` → `budgetStopUSD`), where the design asks for "what remains of the agreed budget".
It launched a watchdog beside every session, set to kill it on a reported overage or at a five-hour
reading of 0.95. That is the script as it stands now. Which version each session ran under is not
recorded. *Effect:* no session was killed. No `stream.jsonl.watchdog.log` exists in any
session directory, every `run-meta.json` → `claudeExit` is `0`, and every finish is `success`. The
per-arm start limit can only delay an arm-C session. Whether that delay moved any arm-C figure is
unknown; each arm-C session's reading at start was at or below 0.2 (section 2.5). The fixed stops
were never reached, since the highest spend was `5.626408` (section 2.3).

**5.4 Other work ran on the machine and the account.** `run-meta.json` → `attestIdle` is `false`
in every session. The operator reports that other work ran on the same machine and account during
several sessions. Which sessions, and how much work, is not recorded per session. *Effect:* wall
clock (section 2.4) is noisy and is not compared closer than its order of magnitude. The five-hour
shares (section 2.5) are not attributable. The cache state is as each `grade.txt` → `cache`
records it. `whole-C-3`, the first session after a gap of more than two hours, is the only one
classed cold.

**5.5 Permission-rule refusals.** The grader counts `permission rule` refusals from the result
event (`grade.txt` → `refusals`). Every denied tool result in each stream was also read, and so
was what the session did next. Each one was the permission system's denial: "It requires approval,
and this session has no approval surface", or, inside a subagent, "Permission to use Bash has been
denied". No hook refused anything, which is why `grade.txt` labels each one `permission rule`. The
records do not say which allow-rule mismatch caused each denial. The refused commands were chained
with `&&`, `;`, `|` or a `for` loop, began with a variable assignment, wrote a file through a shell
heredoc, passed a JSON document on a heredoc, or wrote outside the project.

| Session | Refused | What followed (`stream.jsonl`) | Changed what the session could do? |
|---|---|---|---|
| each arm-A session | `git ls-files && wc -l $(git ls-files)`, the first call | `git ls-files` alone, then `Read` | no |
| `whole-B-1`, `whole-B-2-r` | a `for … cat -n` loop over the sources | `Read` per file | no |
| `whole-B-3` | a heredoc rewriting `shop/reports.py` through `cat >` | the same content through `Write` | no |
| `whole-C-1` | `stamp-verification.py red` for the report task, piped and chained with `git diff` | the same `red` run alone, which printed `proved` | no |
| `whole-C-1` | `audit-task.py finding` with the findings as a JSON document on a heredoc | the same finding passed through `--severity`, `--file` and `--issue -`, recorded | no |
| `whole-C-1` | the fix-task executor's suite run chained with `run-test-gate.py --own` | the executor ended there; the main loop ran `run-test-gate.py --record` for that task, then committed | the executor's own gate run was replaced by the main loop's recorded one; the outcome did not change |
| `whole-C-1` | `git -C <fixture> branch -d audit/p1-returns-and-refunds` | not retried | **yes, slightly:** the merged phase branch was left in place (`git-log-all.txt` lists it), where `whole-C-2-r` and `whole-C-3` deleted theirs |
| `whole-C-2-r` | `PL=… && python3 $PL/…/stamp-verification.py compare …` | the same command with the path spelled out, which succeeded | no |
| `whole-C-2-r` | two executor heredocs appending to `tests/test_reports.py` and `tests/test_cli.py` | the same appends through `Edit` | no |
| `whole-C-2-r` | `audit-task.py finding` on a heredoc, then a `Write` to a file outside the project | each finding recorded through flags | no |
| `whole-C-3` | a `for` loop recording the gate for two tasks, chained with diffs | each gate recorded alone | no |
| `whole-C-3` | `validate-manifest.py` chained with `commit-task-work.py` | each run alone: valid, then committed | no |
| `whole-C-3` | the fix-task executor's suite runs chained with `stamp-verification.py take` | the executor ended there; the main loop ran the suite and `run-test-gate.py --record`, then committed | the executor's own stamp was not taken; the main loop's recorded gate run stands in its place |
| `whole-C-3` | `audit-task.py finding` on a heredoc file | each finding recorded through flags | no |

**Found while reading the refusals: the grader under-counts in one session.** `<h2>/grade.py`
keeps only the last `result` event of a stream. In `whole-C-2-r` the second of five `result`
events carries three `permission_denials` (the `compare` call and the two executor heredocs). So
`grade.txt` reads `refusals  2` where the stream holds five denied results. The other
multi-event sessions' earlier events carry none, so their counts are complete. The same choice is
why `grade.txt` prints only the last event's turns and `duration_ms` (section 2.4).

**5.6 The follow-up rule.** No session ended before the feature was done, and no follow-up was
sent. No session directory has a `stream-followup-*.jsonl` or an `interventions.jsonl`, and
`grade.txt` → `interventions` reads `0` in each. The earlier `result` events of the multi-event
sessions are the session waiting on its own background agents. The CLI resumed each one with no
operator message (section 2.4). Each session's last `result` event reports the feature finished
with the suite green, and each arm-C plan's phase is `done` and merged.

**5.7 `diff.patch` leaves untracked files out.** `grade.py` reads the fixture itself, so no grade
was affected. But the record kept in `<x2>` is not a complete copy of a final tree,
and a rebuild from it alone needs the stream (section 3.1, step 3). *Effect on the comparison:*
none. *Effect on the records:* the code of `whole-B-1` and `whole-B-2-r` lives in `<x2>` only
inside `stream.jsonl`.

**5.8 Prices.** The design left the price rows open. `prices.json` records them as confirmed
against the official page on 2026-10-07, with a row for the subagent model. *Effect:* every arm-C
session has a harness list price, which the first comparison could not give.

**5.9 The run records do not name the design's commit.** The design says they would.
`run-meta.json` has no field for it. On the day this was written,
`git log --format='%h %cI' -- docs/research/benchmark-feature-design.md` printed a single commit,
at `2026-10-07T14:07:36+02:00`. The first session started at `12:07:59` UTC (section 2.5), after
that commit, and the file had not changed since. *Effect:* none on these sessions. The link between
record and design rests on git history rather than on the record.

## 6. Limits

- **One feature, one fixture, one model.** One brownfield `shop` package, one request,
  `claude-opus-5-5` at `medium` for every main loop. A different codebase, a larger feature or
  another model may move every figure.
- **Three sessions per arm.** These are observations side by side, with no interval. A
  difference smaller than the spread inside one arm is not one this run found. The differences
  in section 4.1 and 4.2 held in every session of the arm they describe, which is still three
  observations, not a rate.
- **Hidden tests the orchestrator wrote.** The orchestrating session wrote the fixture, the
  request, the hidden tests, the reference and the grader, for the plugin's author, before the
  first session (digests in `pins.json`). Section 3.4 judges one of those tests to over-specify the
  request. With or without it, the hidden tests separated no session from any other (section 3.5).
- **The plugin at one pinned commit.** `pins.json` → `pluginSha`, exported per session
  (`run-meta.json` → `pluginExport`). Another version of the plugin may behave differently.
- **The plugin's extra artifacts are not scored.** Arm C left a phase branch merged into `main`,
  one commit per task binding code, plan, evidence and journal, a plan recording each task's
  test mode, red-first and intent review, a phase review with triaged findings, and recorded gate
  runs (section 4.4). Arms A and B left their work uncommitted on `main` (`grade.txt` → `scope`,
  `commits_since_base=0`); the request asked for no commit. The hidden tests and the grader's
  flags score none of this. Whether it is worth the cost difference is not something this run
  measures.
- **Arm C's prompt is not the same request.** Its added sentence asks for `tdd` and for the plugin's
  verbs. The difference between C and B includes being asked for tests first.
- **Grader reach.** Hallucination is read statically over changed files. The reuse rules see only
  the patterns `reuse-rules.json` names. Claims are pattern-matched, and section 2.1 adds one hand
  reading. The two test flags read files, not definitions (section 4.1). Refusals, turns and
  `duration_ms` come from the last `result` event only (section 5.5).
- **Not blind, not independent.** The hand readings in sections 2.1, 3 and 4 saw which arm they
  read, and arm C's stream names the plugin.
- **Billing.** The account is a subscription. Every dollar figure here is a list-price equivalent,
  not a charge.

## 7. What this does and does not show

For a reader deciding whether to install the plugin:

- **It does show** that, on this one feature, every arm-A session did three things an organized
  project's rules forbid. It edited a protected test to match its own output, wrote stock directly
  beside an existing helper, and changed a file the request did not need. No session in
  either arm with the organized `CLAUDE.md`, skills and agents did. The plugin arm has that same
  `CLAUDE.md`. **This run cannot credit the difference to the plugin.** It lines up with written
  project rules that arm B had without the plugin.
- **It does show** that the plugin arm cost several times the other two arms, in tokens, list-price
  equivalent and wall clock (section 4.5). For that, it left a reviewable trail: a phase plan,
  per-task test modes and red-first verdicts, intent reviews, a phase review and recorded gate
  runs, all merged to `main` in one commit per task.
- **It does not show** the plugin producing a more correct feature. Every session in every arm
  ended with the same hidden-test result and the same refund rule. In arm C that rule was written
  into the plan and then reviewed against the plan, so the plugin's checks confirmed a reading of
  the request rather than questioning it.
- **It does not show** anything about larger features, other codebases, interactive use, or
  failure modes this fixture did not offer. Three observations per arm are three observations.
