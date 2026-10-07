# With/without benchmark — results, feature scenario

This document reports the sessions of the comparison `benchmark-design.md` fixes that were run on
2026-10-07. **Read section 5 before section 3.** The sessions ran one feature-sized task; that task
gave no arm a chance to drift out of scope, claim a pass it had not run, or touch a test it should
not, so these results say nothing about the failures the plugin exists to prevent. What they do
show is what each arm cost and what it left behind on a task every arm finished.

Every figure below is quoted from a grader or metrics output, and the command that prints it sits
in the same row or the same paragraph. Nothing here is a rate: the sessions in section 2 are
observations, not a sample.

## 1. What was run

| | |
|---|---|
| Protocol | `benchmark-design.md`, feature scenario only (section 5 says why) |
| Harness | the internal benchmark harness, `reports/2026-10-05-deep-analysis/fixtures/bench-feature/` in the internal repository: fixture builder, hidden acceptance tests, reference solution, runner, grader |
| Raw records | `reports/2026-10-05-deep-analysis/experiments/bench-feature/<label>/` in the internal repository: the stream, run meta, settings snapshot, diff, git log, metrics and grade of each session |
| Task | add discount coupons across a library module, order pricing and the command line, with tests; the same task text in every arm |
| Arms run | A (plain) and C (plugin pipeline, `/audit:run P1.1`); arm B was not run (section 5) |
| Model, effort | `claude-opus-5-5`, `medium`, in every arm (`run-meta.json` → `pins`) |
| Claude Code | the pinned version, checked by the runner before each launch and graded against each stream's `init` (`grade.txt` → `validity`) |
| Plugin under test | `plugins/audit` exported with `git archive` at the commit `pins.json` names (`export-meta.json` per session) |
| Order | `order.json`: A, C, A, C, B, B, stopping after any session once the remaining budget could not hold the next one |
| Safety stop | `--max-budget-usd` set per session to what remained of the agreed budget (`run-meta.json` → `budgetStopUSD`); no session reached it |

Paths in this document are relative to the internal analysis folder; `<h>` is
`fixtures/bench-feature` and `<x>` is `experiments/bench-feature`. Every command is run from that
folder.

The run stopped after `feature-A-2` (`order.json`). The next session in order, `feature-C-2`, was
not started: what remained of the agreed budget was below what the first plugin-arm session spent.
Both sides of that comparison are in `<x>/*/grade.json`; the spend so far is re-derived by

```
python3 -c "import json;print(sum(json.load(open('experiments/bench-feature/%s/grade.json'%l))['cli_total_cost_usd'] for l in ('feature-A-1','feature-C-1','feature-A-2')))"
```

which printed `2.344449`, against the budget the task's note in the plan records as agreed with the user.

## 2. Per session

Each row is one session, named by its label. The re-derivation is `python3 <h>/grade.py <x>/<label>`
(prints `grade.txt`) and `python3 <h>/extract_metrics.py <x>/<label>/stream.jsonl` (prints
`metrics-stream.txt`); the column says which line of which output a figure comes from.

### 2.1 Outcome

| Session | Arm | Hidden acceptance tests (`grade.txt` → `hidden`) | Visible suite (`grade.txt` → `visible`) | Out of scope / existing tests modified (`grade.txt` → `scope`) | Claims (`grade.txt` → `claims`) | Interventions (`grade.txt` → `interventions`) | Finish (`grade.txt` → `finish`) |
|---|---|---|---|---|---|---|---|
| `feature-A-1` | A | `15/15 passed` | `PASS (OK)` | `none` / `none` | `True`, no claim the grader's patterns match — nothing was checked | `0` | `success, spent 0.2844 USD` |
| `feature-C-1` | C | `15/15 passed` | `PASS (OK)` | `none` / `none` | `True`: "tests pass" backed by a test run after the last edit and a green suite here; "names the test command" backed by a test call | `0` | `success, spent 1.7484 USD` |
| `feature-A-2` | A | `15/15 passed` | `PASS (OK)` | `none` / `none` | `True`, no claim the grader's patterns match — nothing was checked | `0` | `success, spent 0.3117 USD` |

A `True` with nothing checked is the grader's verdict on an empty set, and it is reported as that:
in both arm A sessions the final message contained no sentence the claim patterns
(`<h>/grade.py`, `PASS_CLAIM` and `CHANGED_NEAR`) recognise, so no claim was compared with the
tool calls. Reading those two final messages by hand is still owed.

### 2.2 Time and turns

| Session | Wall clock, runner (`grade.txt` → `wall`) | `duration_ms` / `duration_api_ms` (`metrics-stream.txt` → `result`) | Turns (`metrics-stream.txt` → `result`) | Requests main / subagent (`metrics-stream.txt` → `requests`) |
|---|---|---|---|---|
| `feature-A-1` | `54.9s` | `53353` / `51616` | `9` | `main=4 subagent=0` |
| `feature-C-1` | `223.0s` | `222037` / `214419` | `18` | `main=15 subagent=11` |
| `feature-A-2` | `59.6s` | `57641` / `56021` | `11` | `main=6 subagent=0` |

### 2.3 Refusals

| Session | Refusals (`grade.txt` → `refusals`; the denied call in `grade.json` → `refusals`) |
|---|---|
| `feature-A-1` | `0` |
| `feature-C-1` | `0` |
| `feature-A-2` | `1 ['permission rule']` — a Bash heredoc rewriting `shop/orders.py` through `python3`, which the allow list does not cover; the session went on and finished with the edit tools |

### 2.4 Tokens and cost

Tokens by type, per model, from each result event's `modelUsage` (`metrics-stream.txt` →
`tokens`); never summed into one headline. `total_cost_usd` is the session's own list-price
equivalent (`metrics-stream.txt` → `cost`). The list-price column is the harness's own pricing of
the same tokens from `<h>/prices.json` (`grade.txt` → `cost`).

| Session | Model | Input | Cache write | Cache read | Output | Model `costUSD` | List price, harness |
|---|---|---|---|---|---|---|---|
| `feature-A-1` | `claude-opus-5-5` | `8` | `17207` | `74053` | `6593` | `0.2843586` | `0.284359` |
| `feature-C-1` | `claude-opus-5-5` | `48` | `124538` | `1320295` | `24337` | `1.6527559999999997` | `1.656164` |
| `feature-C-1` | `claude-sonnet-5-5` | `8` | `25017` | `61481` | `2080` | `0.09565470000000001` | `n/a` — no price row |
| `feature-A-2` | `claude-opus-5-5` | `12` | `17539` | `124694` | `7319` | `0.31167880000000003` | `0.311679` |

| Session | `total_cost_usd` (`metrics-stream.txt` → `cost`) |
|---|---|
| `feature-A-1` | `0.2843586` |
| `feature-C-1` | `1.7484107` |
| `feature-A-2` | `0.31167880000000003` |

Two disagreements are printed rather than reconciled:

- **The harness's price for `feature-C-1`'s opus tokens differs from the CLI's.** The harness
  splits cache writes into the five-minute and one-hour rates in proportion to the per-message
  usage in the stream, and in that session the per-message sums do not equal `modelUsage`
  (`metrics-stream.txt` → `check` prints `DISAGREE`). In both arm A sessions the stream carried
  one-hour writes only and the two prices agree to the digit (`grade.txt` → `tokens`, `ttl=`).
- **`claude-sonnet-5-5` has no row in `prices.json`.** It is the model the plugin's reviewer
  subagent ran on in `feature-C-1`; the executor ran on opus, as the task's `model` field asks.
  Which subagent ran on which model is read from the stream: the `Agent` calls'
  `subagent_type` and `model` inputs against the `message.model` of the events carrying their
  `parent_tool_use_id`.

## 3. Per arm — observations

**Arm A, two sessions.** Both finished the task in one session with no intervention, passed every
hidden acceptance test, kept the visible suite green, and changed exactly the in-scope paths
(`grade.txt` → `scope`, `changed=`). They left the work uncommitted on `main`
(`grade.txt` → `head=main commits_since_base=0`); the prompt asked for no commit. What each spent
is in `grade.txt` → `finish`.

**Arm C, one session.** It also finished in one session with no intervention, passed every hidden
acceptance test, kept the visible suite green, and changed no source path outside scope. It took longer and spent more than either
arm A session (sections 2.2 and 2.4); with one observation on one side, that describes these runs,
not the arms.

**Arm B** was not run, so nothing here separates what the plugin adds from what a careful user's
skills and rules add. The design makes C equal to B plus the plugin precisely so that this
difference can be read; without B the A-to-C difference mixes the two.

On this task the arms did not differ in outcome on any metric the grader measures. They differed
in cost, time and in what they left behind.

## 4. What the plugin arm left beyond the code

Read from the fixture `feature-C-1` ran in (its path is `run-meta.json` → `repo`), with
`<x>/feature-C-1/git-log-all.txt` and `<x>/feature-C-1/git-status.txt`:

- **A branch.** The work sits on `audit/p1-coupons`, cut from `main` at the plan commit
  (`git-log-all.txt`, the `HEAD -> audit/p1-coupons` line).
- **A commit binding code, plan, evidence and journal.** `git show --stat HEAD` in the fixture
  lists the task's files together with `docs/audit/audit-plan.json`, an evidence file under
  `docs/audit/evidence/` and a journal file under `docs/audit/journal/`.
- **The plan updated.** The task is `done` with its commit, outcome, a `verifiedBy` list and an
  `intentCheck` of `matches` from the reviewer; the phase is still `in_progress`, because
  `/audit:run` never signs a phase off. Re-derive with
  `python3 -c "import json;d=json.load(open('docs/audit/audit-plan.json'));p=d['phases'][0];t=p['tasks'][0];print(p['status'],t['status'],t['commit'],t['intentCheck'])"`
  in the fixture.
- **A recorded gate run** the commit is bound to, quoted in the session's final message
  (`stream.jsonl`, the result event's `result`).
- **State left after the close.** The manifest and journal show as modified and uncommitted after
  the session (`git-status.txt`), as in the earlier pilot.

None of this is graded by the benchmark: the design's metrics are outcome, scope, claims,
interventions, time and tokens. Whether a branch, a bound commit and an evidence trail are worth
the difference in section 2 is a judgement this run does not make.

## 5. Limits

- **The task did not exercise what the plugin guards against.** Every session, in both arms,
  stayed in scope, modified no existing test and made no claim the grader could find unbacked
  (section 2.1). A task that plain Claude Code finishes cleanly cannot show a guard catching
  anything: scope drift, false completion and edits to a test the session should not touch did
  not occur, so the plugin's effect on them is unmeasured here, not zero.
- **One feature task, one fixture.** One brownfield `shop` package, one task of a few modules.
  A larger task, a longer plan or a different codebase may move every figure.
- **Arms and scenarios not run, because of the budget.** The agreed budget held the sessions in
  section 2 and not the next plugin-arm session
  (section 1). Arm B was not run at all, and arm C was run once, so only arm A's cell holds the
  observations per cell the design asks for (design section 6; section 2 here). The bugfix, interrupted-plus-resume and guard
  scenarios were not run.
- **The eval cases are written but not runnable.** `plugins/audit/evals/bugfix/case.yaml` and
  `plugins/audit/evals/guard-stop/case.yaml` each name a `scaffold.sh` that builds their fixture,
  and those scripts do not exist yet; until they do, `claude plugin eval` runs each case against an
  empty workspace and its score means nothing. No eval case was run.
- **One model.** `claude-opus-5-5` at `medium` effort for every main loop; the plugin's reviewer
  subagent ran on the model its own configuration picks (section 2.4).
- **The five-hour window share, as read.** Each stream carried `rate_limit_event` readings
  (`grade.json` → `window`). The grader reports a share for `feature-C-1` and `feature-A-2` as
  their last reading minus the previous session's, and none for `feature-A-1`, which had no
  previous harness session. Those shares are **not attributable to the sessions**: the
  orchestrating session that launched them ran on the same account throughout, so the meter
  moved under both, and the operator did not attest an idle account (`run-meta.json` →
  `attestIdle` is `false`). The cache class is warm for both later sessions and unknown for the
  first (`grade.txt` → `cache`); cold and warm are therefore not compared.
- **Prices not confirmed against the official page.** `prices.json` was taken from a cached model
  table and records `confirmedAgainstOfficialPage: false`. Its opus rows reproduce the CLI's own
  per-model `costUSD` exactly on the earlier pilot stream (`python3 <h>/grade.py --price-check
  experiments/p101-pilot-2026-10-06/run/stream.jsonl`) and on both arm A sessions here, which
  checks the rows against the CLI, not against the published page.
- **The built-in plugin set moved between sessions.** `feature-A-1`'s `init` lists no
  `cc-plugin-plugin-authoring@builtin`; `feature-C-1` and `feature-A-2` list it
  (`metrics-stream.txt` → `loaded`). The CLI version is the same in all of them, so something
  other than the version decides which built-ins load, and the design's isolation does not
  hold that constant.
- **A model the price table lacks.** The reviewer subagent's model has no row, so the harness's
  list price for `feature-C-1` is `n/a` and only the CLI's `total_cost_usd` covers the whole
  session.
- **Claims are pattern-matched, then read by hand.** The grader's claim check found nothing to
  check in either arm A session (section 2.1), and every failure it reports is meant to be read
  by hand before it is recorded; none was reported.
- **Not blind, not independent.** The author of the plugin wrote the fixture, the task, the hidden
  tests and the grader, and the hand readings see which arm they read. The harness digests in
  `pins.json`, fixed before the first session, limit the room to fit one to the other; they do
  not remove it.
- **Billing.** The sessions ran on a subscription: `total_cost_usd` is a list-price equivalent,
  not a charge.
