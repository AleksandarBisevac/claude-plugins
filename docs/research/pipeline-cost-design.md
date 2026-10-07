# Pipeline cost design — cutting the fixed part without spending a guarantee

[pipeline-cost-analysis.md](pipeline-cost-analysis.md) measured what a pipeline run pays for. This
document decides what to change. It compares each candidate change on the same criteria, recommends
one structure, and breaks it into implementation tasks. Each task has a target a tool can re-derive,
and each names the benchmark session that will confirm or refute it.

It builds on two earlier documents and does not repeat them. The analysis supplies the stage and
class costs. [token-efficiency-audit.md](token-efficiency-audit.md) supplies an earlier backlog of
recommendations, which section 0.1 checks against the tree. No model call was made to write this
document.

**Revised for the cost target (2026-10-07).** The user then set a target the earlier recommendation
does not meet (section 0.2). This revision answers it with mechanisms: a script that drives the
pipeline, verbs that compute what the model used to type, and agent definitions. It adds:

- the whole-feature sessions decomposed by span and by origin (sections 1.5 and 1.6);
- the candidates the target named (C9 to C15, section 3);
- a ladder from today to the target, with the recommended set and the decisions it needs
  (section 5);
- the implementation tasks restated, each with a micro-test (section 6);
- the order of measurement: micro-tests first, the full benchmark last (section 7).

What the target overturns is kept once as dated history: the earlier set and its prediction in
section 5.5, the earlier task targets beside the tasks that replace them.

## 0. How to read this

| Label | Means |
|---|---|
| **measured** | printed by a tool from a session record or a git ref; the command is beside it |
| **derived** | arithmetic on measured figures; the arithmetic is written out |
| **estimate** | a figure that rests on a stated judgement, such as which sections a step needs |
| **prediction** | what a change is expected to save, computed by the model in section 1 from measured figures; never a result |
| **inference** | reasoning from the above; not evidence |
| **unknown** | a host behaviour the official documentation does not state; section 9 lists each one and the choice that depends on it |

Paths follow the analysis. `<x>` is `experiments/bench-feature` in the internal repository's analysis
folder, and `<p>` is `experiments/p101-pilot-2026-10-06/run` there. `<x2>` is
`experiments/bench-feature-v2` and `<h2>` is `fixtures/bench-feature-v2`, the whole-feature benchmark.
Its protocol is `docs/research/benchmark-feature-design.md`, which **lands with the whole-feature
benchmark phase**. When this was written, that file was on that phase's branch
(`audit/p116-a-whole-feature-in-an-existing`, commit `a289dcbb`) and on neither this branch nor
`main`: `git cat-file -e <ref>:docs/research/benchmark-feature-design.md` answers for each. Until that
phase merges, read the protocol at `a289dcbb`. Commands run from this repository's root.

**Every command is pinned to what its figures were taken at.** The plugin's prose is measured at
`7b489337`, and `git diff --stat f7eaade4 7b489337 -- plugins/audit` prints nothing, so it is also
the plugin the whole-feature study runs. The `stream-cost.py` and `measure-context.py` figures are
those tools' output at `9501aa91`. Re-derive them from a checkout of that commit. T1 changes both
tools, so a pin that followed this document's latest commit would point at a tool these figures did
not come from.

One part of T1 has landed: `stream-cost.py` reads every `result` event, from the commit
`git log --format=%h -S'def session_result' -- tools/stream-cost.py | tail -1` prints, called the
result-reading commit below. Which pin a figure carries follows from it:

- **`9501aa91` stays** on every `stream-cost.py` figure of `feature-C-1`, `feature-A-1`,
  `feature-A-2` and the pilot. Each holds one result event (`grep -c '"type":"result"'
  <record>/stream.jsonl`), and the result-reading commit prints each of them byte for byte as
  `9501aa91` does, in text and with `--json`. Section 10's cycle command prints the same two lines
  at both commits.
- **The result-reading commit** carries the figures of the arm C sessions `whole-C-1`,
  `whole-C-3` and `whole-C-2-r` that section 6, T1, quotes as read by it. `9501aa91` cannot price
  those sessions, and its readings of them stay pinned to it as the evidence of why.

Prices are the plugin's shipped table,
`_usage_core.DEFAULT_PRICING`. For
`claude-opus-5-5` the rates per million tokens are: input 4.0, output 20.0, five-minute write 5.0,
one-hour write 8.0, cache read 0.2. The reviewer in `feature-C-1` ran on a model that resolves to the
`claude-sonnet-5` row: five-minute write 2.5, cache read 0.2, output 10.0. Bytes become tokens at the
calibrated 2.63 bytes per token (the analysis, section 6.1).

**Every session here was run once.** Each figure from a session is one observation of that session.
None is a rate.

**Revised after review.** The first draft predicted a one-task run falling from `1.7485` to `0.9962`
and a five-task run from `6.7077` to `3.9486`. A review of that draft found terms counted under the
wrong multiplier and figures with no arithmetic shown. Section 1.2 now:

- counts the per-task requests in two shapes, eight and six (section 1.1);
- keeps out the re-read term the measured task class already held;
- separates the task work a run pays once from the work it pays per task;
- writes out the early reads the run line had left implicit;
- removes the two one-off requests by position, as section 5.5 counts the after state.

`stream-cost.py` now classes the bytes an `Edit` emits by the path it writes, which moved the main
loop's edit of the plan from the file class to the task class. Every figure below is re-derived on
that basis.

Every per-task target and confirming reading reads one span, the task cycle: main-loop requests
bounded by two calls the stream records (section 1.1). Planning, the run's own requests and
sign-off fall outside it.
So no reading subtracts them from a whole-session table, which is how earlier revisions let that
work flatter or refute a target their prediction never counted.

### 0.1 Where the earlier backlog stands

Read off the tree on 2026-10-07, so this design starts from what shipped rather than from what was
proposed:

| Earlier recommendation | State | Command |
|---|---|---|
| R1, split the reference prose | partly: `execute-task.md` and `phase-signoff.md` are their own files, and every other file is still read whole | `ls plugins/audit/reference` |
| R2, project the discovery payload | shipped | `grep -n "section discovery" plugins/audit/commands/init.md plugins/audit/commands/task.md` |
| R4, descriptions out of startup context | shipped | `grep -l disable-model-invocation plugins/audit/commands/*.md` |
| R5, `omitClaudeMd` | not shipped | `grep -rl omitClaudeMd plugins/audit/agents` prints nothing |
| R6, bound the agent | `executor.maxHours` shipped, `maxTurns` not | `grep -n maxHours plugins/audit/schema/audit-config.schema.json` |
| R7, `experimental.cacheTtl` | not shipped | `grep -rn cacheTtl plugins/audit/agents` prints nothing |
| R8, `review.perTask` | not shipped | `grep -n perTask plugins/audit/schema/audit-config.schema.json` prints nothing |

R8 and R7 come back below as C5 and part of C6, re-priced with the measured stage costs.

### 0.2 The cost target, and the two measures every rung is read in

The user set the target on 2026-10-07, in two parts:

1. **Per task.** The plugin's task cycle may cost at most twice what plain Claude Code spends on the
   same task, and ideally 1.25 times.
2. **Per phase.** Planning, the phase review and the phase gate are a phase overhead with a budget
   of their own. Each part of it is justified by what it catches, measured, or it is a candidate
   for removal.

The user asked for the infrastructure and mechanisms that cut every cost that is not needed, down to
the minimum the guarantees require. So the answer below is mechanisms. Prose is cut only where a
script, a verb or an agent definition takes its place.

**The two measures**, read on the whole-feature benchmark's nine valid sessions (section 1.5):

- **The per-task ratio.** The task cycle's billed cost, divided by arm A's mean session cost. The
  cycle is section 1.1's span: the main-loop requests from the first `start` to the last `done`
  before a request inside it plans, plus every request of the agents those requests dispatched.
  Arm A did the same tasks in one session, so dividing both sides by the tasks the cycle holds
  leaves the ratio unchanged. The description leaves the plain side open. This revision takes the
  whole plain session, because it is the only plain figure for the same tasks.
- **The whole-feature ratio.** The session's total, divided by arm A's mean and by arm B's mean.
  Arm B matched the plugin arm on every graded measure (the results document's section 4.6), so B
  is the price reference: what the plugin costs beyond B has to buy something measurable.

**The phase overhead** is everything in an arm C session outside the task cycle: planning, the
run's own preflight, sign-off with any fix task it runs, and the run's close.

**The plain figures.** Arm A's mean is `0.547004`, derived: (0.505336 + 0.600682 + 0.534995) / 3.
Arm B's mean is `0.843470`, derived: (0.764088 + 0.735201 + 1.031121) / 3. Each session's figure is
`all models priced` in `python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`, which equals that
session's `total_cost_usd` (section 1.5.1). The results document is
`docs/research/benchmark-feature-results.md`, which lands with the whole-feature benchmark phase: on
the day this was written it was at `186fcf7d` on that phase's branch and on neither this branch nor
`main`.

**Pins for the new readings.** Every figure in sections 1.5, 1.6 and 5 comes from the result-reading
commit's `stream-cost.py` (section 0), from its own report, or through section 10's commands. The
span, billed-span and output-kind commands call the tool's own `analyse()`. The injection, gap and
agent-calls commands read the stream alone. All of them read records that do not change.

## 1. The cost model every prediction uses

### 1.1 Inputs

Every input is from `feature-C-1`, which on 2026-10-07 was the only recorded plugin session that had
built a feature. Unless the
row says otherwise, the command is `python3 tools/stream-cost.py <x>/feature-C-1/stream.jsonl`, with
`--json` for the `requests` and `items` arrays.

| Input | Value | Where it is printed |
|---|---|---|
| total, priced | `1.748411` | `pricing:` → `all models` |
| run class: write, carry, output, total | `0.5406`, `0.2017`, `0.0109`, `0.7532` | `by content class` |
| task class total | `0.7823` | same |
| file class total | `0.2129` | same |
| reference prose written once | 57417 tokens, derived: 21913 + 21875 + 13629 | `largest cache writes`, the three `Read <plugin>/reference/…` rows |
| later main-loop requests that re-read it | 12 | the `reads` column of those rows |
| what those rows cost | `0.5971`, derived: 0.2279 + 0.2275 + 0.1417 | their `$total` |
| run-class tokens a further main-loop request reads | 79461 | `contexts:` → `main`, `run` |
| main-loop reads before the prose was written | 54899 tokens, derived: 11891 + 21195 + 21813 | `--json` → `requests`, the `cr` of the first three main-loop requests |
| task-class tokens left in the main loop after the task | 25455 | `contexts:` → `main`, `task` |
| ...of which the task cycle's requests put there | 21857 | `--json` → `items` of the main context, each counted for the request before the one its `request` names, which cached it (section 1.2); or section 10's cycle command |
| price of one more request, main loop / executor / reviewer | `0.0210` / `0.0063` / `0.0050` | `contexts:` → `$/request` |
| main-loop requests | orient 2, plan 5, gate 3, close 5; the task cycle holds 8 | `per stage, as billed` → `req`; the cycle, section 10's cycle command |
| agent starts | executor 16952 tokens, five-minute write on opus (`0.0848`); reviewer 15878, on the sonnet row (`0.0397`) | `largest cache writes`, `agent start` rows |
| briefs typed by the main loop | 2840 and 2817 output tokens (`0.0568`, `0.0563`) | `largest outputs` |
| main-loop output | 14031 tokens | `output pool, measured: main loop` |
| ...of which the task cycle's requests emitted | 11374 tokens, an estimate: the pool apportioned by emitted bytes | section 10's cycle command, or the `out` of requests 6 to 13 in `--json` → `requests` |

**Which main-loop requests are per task.** The main loop's tool calls and text were listed from the
stream:

```
python3 -c "import json,sys
for l in open(sys.argv[1]):
    e=json.loads(l)
    if e.get('type')!='assistant' or e.get('parent_tool_use_id'): continue
    for c in e['message']['content']:
        if c.get('type')=='tool_use': print(e['message']['id'][-6:], c['name'], str(c['input'])[:90])
        elif c.get('type')=='text': print(e['message']['id'][-6:], 'text', c['text'][:200])
" <x>/feature-C-1/stream.jsonl
```

The task cycle, defined below, decides which requests are per task: in `feature-C-1`, requests 6 to
13. After the request that wrote the prose, the run-level requests outside it are the manifest
read, the lock, the lock release and the report. Which of the cycle's requests are steps and which
happened because something went wrong is inference, read off their tool calls and text: six steps,
and two one-offs. The six steps:

1. the task start;
2. the executor dispatch;
3. the gate run, with the stamp comparison in the same call (the request ending `nt66Ew`);
4. the reviewer dispatch;
5. the commit;
6. the close.

`feature-C-1` made two more, and each was one observation:

- **a re-check after the stamp came back stale** (`yyXaVM`, whose text reads "The stamp came back
  stale, so I'll check which field moved");
- **a retried close** (`avGJjL`), after zsh passed the verb's test list as one word.

Whether either recurs is unmeasured. So every prediction below is given twice, at `k` = 8 requests
per task as `feature-C-1` recorded them and at `k` = 6 without the two. The pilot's main loop made
17 requests (`python3 tools/stream-cost.py <p>/stream.jsonl`, the `req` column), so the shape
varies between runs. This list and the analysis's section 4 describe the same requests.

**The task cycle.** Every per-task target and confirming reading in this document reads one span of
main-loop requests, bounded by calls the stream records:

- it opens at the first request that calls `audit-task.py start`;
- it closes at the last request that calls `audit-task.py done` for a task, before any request
  inside the span plans one. A request plans when it makes a `Skill` call to `audit:phase` or
  `audit:task` whose `args` begin with `add`, or calls the `add` or `add-phase` verb.

The tasks it holds are the ids its `done` calls name, and their count is the `N` a per-task reading
divides by. Planning falls outside the cycle by construction: it comes before the first start, and
a task planned later closes the cycle. The run's opening requests (preflight, manifest read, lock)
and its closing ones (lock release, report) fall outside it in the order the run's prose gives
them, before the first start and after the last `done`.

Sign-off is what the second half of the closing rule is for. Sign-off runs once every task is done
(`reference/phase-signoff.md:11` at `7b489337`), and for each actionable finding it has the main
loop create and start a task (`:71`). A cycle closed at the last `done` of any task would hold
sign-off's review and its fix tasks. A task planned inside the cycle closes it at the `done` before,
so the fix tasks fall after the cycle with the rest of sign-off. That order is the prose's. Nothing
stops a main loop dispatching sign-off's reviewer before its last task closes, and a cycle read from
such a session would hold the review. What falls outside the cycle is counted apart, never
subtracted from a reading.

In `feature-C-1` the cycle is requests 6 to 13. The table lists every main-loop request in stream
order, with its output and the task-class tokens it put into the main loop's cache. The stream
writes those tokens at the next request. Output is apportioned within the measured pool by emitted
bytes, so that column is an estimate, and it sums to 14031 before rounding.

| # | Request | What it did | Where | `out` | task tokens |
|---|---|---|---|---|---|
| 1 | `7cvhXJ` | sizes the three reference files | orient | 205 | 0 |
| 2 | `9EwTxN` | reads them | orient | 341 | 0 |
| 3 | `e5FBL8` | the preflight; the prose enters the cache | the run's own | 164 | 692 |
| 4 | `r4YX8x` | reads the manifest | the run's own | 142 | 1847 |
| 5 | `RWqWTm` | validates it and takes the lock | the run's own | 353 | 653 |
| 6 | `eknkfg` | marks the phase running, then `start P1.1` and the brief lookup | **opens the cycle** | 557 | 2616 |
| 7 | `JgzmC5` | the executor dispatch | cycle | 2840 | 5159 |
| 8 | `nt66Ew` | the recorded gate, with the stamp comparison | cycle | 675 | 1458 |
| 9 | `yyXaVM` | the re-check of the stale stamp, a one-off | cycle | 630 | 1229 |
| 10 | `5JJjhV` | the reviewer dispatch | cycle | 2817 | 3646 |
| 11 | `fFRT6p` | the commit, then `done --help`, which names no task | cycle | 362 | 1195 |
| 12 | `CLGcxV` | `done P1.1`, refused with exit 2 | cycle | 1723 | 2985 |
| 13 | `avGJjL` | `done P1.1` again, which closes it; a one-off | **closes the cycle** | 1769 | 3569 |
| 14 | `84rhDm` | releases the lock | the run's own | 212 | 406 |
| 15 | `FSeULu` | the report | the run's own | 1239 | 0 |

The cycle holds every per-task figure section 1.2 rests on. Section 10's cycle command prints them
from the pinned tool's own reading, for requests 6 to 13 and the two agents they dispatched:

- 8 requests, which is `k` at 8;
- 21857 task-class tokens, which is `c` at k = 8;
- a task class of `0.704895`, which is `t` at k = 8, and a file class of `0.212897`, the file term;
- 11374 output tokens, an estimate.

So the task class outside the cycle is 0.782339 − 0.704895 = `0.0774`, which is L(12). Section 1.2
takes that part out of `t` by arithmetic, and the cycle leaves it out by position. Requests 3 to 5,
14 and 15 are the five that section 1.2 names, and orient's requests put no task-class content
there (`per stage, by what it put there`, the `orient` row). The cycle's unit is a request.
Request 6 marks the phase running, which a run does once, and the cycle holds that because the same
request started the task. Section 1.2's `c` already counted it so.

**Read against arm C.** `whole-C-3` was recorded later on 2026-10-07 (`<x2>/whole-C-3`). Whether it
is valid for the whole-feature study is that study's question. It is read here only for where the
rule puts its bounds, with section 10's event command:

- its main loop planned from request 1, a `Skill` call to `audit:phase` with `args` `add`, through
  the `add-phase` and `add` verbs at 9 to 12;
- a second `Skill` call, `audit:phase P1`, came at 13, and request 14 ran the preflight and took the
  lock;
- the cycle is requests 15 to 36 and holds P1.1, P1.2 and P1.3, the last two run in parallel;
- at 37 the main loop added a fix task for the findings P1.1's reviewer had raised (recorded at 19),
  and at 38 it started that task, its text reading "I'm now in phase sign-off"; the task closed at
  44;
- sign-off's own review followed at 47, and the sign-off at 55.

Closed at the last `done`, the cycle would have held requests 37 to 44 too. `9501aa91` cannot price
the session, and the result-reading commit can (section 6, T1). Section 1.5 reads it, with
`whole-C-1` and `whole-C-2-r`, by these bounds.

### 1.2 The formulas

Notation: `w` is the one-hour write rate 8.0e-6, `r` the cache-read rate 0.2e-6 and `o` the output
rate 20e-6, each per token for the main loop's model. `N` is the number of tasks a run executes and
`k` the main-loop requests per task, 8 or 6 (section 1.1). `m = 4 + kN` is the number of main-loop
requests after the one that wrote the prose; in `feature-C-1` it was 12. Sums are taken before
rounding, so a total can differ in its last digit from the sum of the rounded parts shown.

- **Prose.** `T` prose tokens are written once and re-read by every later main-loop request:
  `T × (w + r × m)`. Check against `feature-C-1`: 57417 × (8.0 + 0.2 × 12) / 10^6 = `0.5971`, which
  equals the measured rows.
- **Run class.** `R(m) = W + O + E + P × r × m`, where:
  - `W` = `0.5406`, the run class `$write`;
  - `O` = `0.0109`, its `$out`;
  - `E` = `0.0110`, the reads made before the prose was written (54899 × 0.2 / 10^6);
  - `P` = 79461, the run-class tokens every later request reads.

  Check: 0.5406 + 0.0109 + 0.0110 + 79461 × 0.2 × 12 / 10^6 = `0.7532`, the measured run class. The
  first draft scaled the whole measured carry by m / 12, which charged every added request a share of
  the early reads as well.
- **Task work a run pays once.** Five main-loop requests are not per task: the one that wrote the
  prose (it also ran the preflight), the manifest read, the lock, the lock release and the report.
  They are the requests outside the task cycle other than orient's (section 1.1). The tool classes
  their work as task work, by its rule, but a run pays it once:
  `L(m) = U + (H × m − G) × r`, where:
  - `U` = `0.0711`: their output, 2111 tokens × o = 0.0422 (`--json` → `requests`, the `out` of those
    five); their input, 0.00004; and the content they added to the cache, 3598 tokens × w = 0.0288
    (692 + 1847 + 653 + 406, from `items`, grouped by the request that produced each);
  - `H` = 3192, the part of that content every per-task request reads (692 + 1847 + 653);
  - `G` = 6345, the reads that content misses because it enters the cache one, two and three
    requests into the `m` (692 × 1 + 1847 × 2 + 653 × 3).

  At m = 12: 0.0711 + (3192 × 12 − 6345) × 0.2 / 10^6 = `0.0774`.
- **Task work paid per task.** `t × N + c × r × k × N(N−1)/2`, where:
  - `t` = `0.7049` at k = 8: the task class less L(12), that is 0.7823 − 0.0774. The task cycle's
    own task class reads the same (section 1.1);
  - `c` = 21857 at k = 8: the content the task cycle's requests leave in the main loop
    (2616 + 5159 + 1458 + 1229 + 3646 + 1195 + 2985 + 3569);
  - the square term holds the reads of `c` by every request of every later task.

  The release and the report read every task's content once, and `t` already holds that read, so it
  has no term of its own. The first draft added `2 × (N−1)` such reads and so counted them twice.

  For k = 6, both come from `feature-C-1` less its two one-off requests. `c` = 21857 − 1229 − 3569
  = 17059. `t` = 0.7049 − 0.0936 = `0.6113`, where 0.0936 is what those two requests cost:
  - their output, (630 + 1769) × o = 0.0480;
  - their input, 0.00002;
  - the content they added, (1229 + 3569) × w = 0.0384;
  - the reads of per-task content they take away, (99642 − 63636) × r = 0.0072. Both counts are by
    position, as section 5.5 counts the after state: a row enters the cache at the request after the
    one that made it, and every later main-loop request reads it. Today's eight-request shape gives
    2616 × 8 + 5159 × 7 + 1458 × 6 + 1229 × 5 + 3646 × 4 + 1195 × 3 + 2985 × 2 + 3569 × 1 = 99642.
    The six-request shape gives 2616 × 6 + 5159 × 5 + 1458 × 4 + 3646 × 3 + 1195 × 2 + 2985 × 1 =
    63636.

  The 36006 tokens between the two are, by request:
  - the re-check's own reads, 2616 + 5159 = 7775;
  - the retry's own reads, 7775 + 1458 + 1229 + 3646 + 1195 = 15303;
  - the reads of their content by the requests that remain, 1229 × 4 + 3569 × 1 = 8485;
  - two reads that move. With the re-check gone, the reviewer dispatch writes the gate's 1458
    instead of reading it, and with the retry gone the lock release writes the close's 2985.

  7775 + 15303 + 8485 + 1458 + 2985 = 36006. The count of today's shape is the measured one too:
  the `cr` of each main-loop request from the executor dispatch to the report (`--json` →
  `requests`) sums to 843519, and 843519 − 9 × (79461 + 3192) = 99642.

  The revision at `9501aa91` gave `0.0925` and `0.6124`. It subtracted the re-check's 1229 from the
  retry's reads without counting it anywhere else, and it left out both moved reads: 5672 tokens in
  all (1229 + 1458 + 2985).
- **File class.** `0.2129 × N`. This assumes every task is the size of `feature-C-1`'s task.

**Prediction, today's pipeline:**

| | k | m | run | task, once per run | task, per task | file | total |
|---|---|---|---|---|---|---|---|
| N = 1 | 8 | 12 | `0.7532` | `0.0774` | `0.7049` | `0.2129` | `1.7484` (measured: `1.748411`) |
| N = 1 | 6 | 10 | `0.7214` | `0.0762` | `0.6113` | `0.2129` | `1.6217` |
| N = 5 | 8 | 44 | `1.2617` | `0.0979` | `3.8742` | `1.0645` | `6.2983` |
| N = 5 | 6 | 34 | `1.1028` | `0.0915` | `3.2613` | `1.0645` | `5.5200` |

The per-task work grows with the square of `N`. At N = 5 that term is `0.3497` at k = 8 (derived:
21857 × 0.2e-6 × 8 × 10) and `0.2047` at k = 6 (17059 × 0.2e-6 × 6 × 10). No single-task record can
show it.

### 1.3 What a kilobyte costs, by where it sits

Derived from the rates and the request counts above. This is why the main loop's prose comes first:

| Where the bytes are | Price per 1000 bytes (380 tokens) | Arithmetic |
|---|---|---|
| main-loop prose, N = 1 | `0.00395` at k = 8, `0.00380` at k = 6 | 380.2 × (8.0 + 0.2 × m) / 10^6, m = 12 or 10 |
| main-loop prose, N = 5 | `0.00639` at k = 8, `0.00563` at k = 6 | the same, m = 44 or 34 |
| executor system prompt, per dispatch | `0.00251` | 380.2 × (5.0 + 0.2 × 8) / 10^6; the executor made 9 requests |
| reviewer system prompt, per dispatch | `0.00118` | 380.2 × (2.5 + 0.2 × 3) / 10^6; the reviewer made 4 |
| one main-loop output token | `0.0000200`, then re-read at `0.0000002` per later request | the output rate |

### 1.4 What the model cannot see

None of the sessions this model is computed from reached these, so each is an assumption or an open
question for the benchmark in section 7:

- **sign-off.** `/audit:phase` ends with it, and both recorded plugin sessions were `/audit:run`
  (`cat <x>/feature-C-1/prompt.txt <p>/prompt.txt`). Where a figure needs sign-off, `S` = 6 main-loop
  requests is assumed. `phase-signoff.md` numbers five steps, and the first of them spawns a reviewer.
  That is an assumption, and T5 replaces it with a reading. No per-task reading needs `S`, because
  sign-off falls after the task cycle (section 1.1). `whole-C-3`, recorded later, reached sign-off.
- **planning verbs.** The calibration session planned nothing. `feature-C-1`'s prompt is
  `/audit:run P1.1` (`cat <x>/feature-C-1/prompt.txt`), and its main loop made no `Skill` call and
  no `add` call of either verb (section 1.1's snippet lists every call). Whole-feature arm C does
  plan. Its prompt is the request with `<h2>/plugin-sentence.txt` appended (`<h2>/run_session.py`,
  `prompt_for`), which asks for `/audit:phase add` and `/audit:task add` before the run. Today's
  stage rule makes every request from the end of orient to the first executor dispatch `plan`
  (`stream-cost.py`'s docstring, *STAGES*), so a reading of that table would count those planning
  requests as task work. The task cycle cannot hold them, because they come before its first start
  (section 1.1). T1's `planning` row prints them apart, for section 7's whole-set reading and for C8.
  How many times a session invokes each verb, and whether every invocation injects the command body
  again, is unmeasured.
- **parallel waves.** The formula treats tasks as serial.
- **a second dispatch of one agent type.** Whether it reads the first dispatch's cache is unmeasured.
- **gaps.** How long the main loop waits between requests decides the cache-TTL question (C6).
- **the main loop's TTL, and the billing it follows.** Every dollar figure prices main-loop writes at
  `w` = 8.0, the one-hour rate, because `feature-C-1`'s main loop wrote at it (the `cacheW1h` column).
  The host facts give one hour as the default only on a Claude subscription within its plan's
  included usage. Usage credits, an API key and a cloud provider get five minutes, at 5.0. So for
  those users every main-loop write term here is an overstatement by three eighths. C6a prices that
  difference, and which TTL a given user's main loop gets is **unknown** to the plugin (section 9).
- **the two one-off requests.** Whether a stale stamp's re-check and a retried close recur is
  unmeasured. That is why each prediction is given at k = 8 and at k = 6.
- **which requests are per run.** In the model, the five that section 1.2 names, read off one
  session's tool calls (section 1.1). A run that, say, re-reads the manifest per task moves work from
  `L` to `t`. A cycle reading of that run places the re-read inside the cycle by its position, so the
  reading follows the move and the model does not.

**Each of those, as the whole-feature sessions read it.** T5's target was a reading beside every
assumption above. These are one observation per session, from section 1.5:

| Assumption | Reading, `whole-C-3` / `whole-C-1` / `whole-C-2-r` |
|---|---|
| `S` = 6 sign-off requests | sign-off held 13 / 8 / 10 main-loop requests, a fix task a further 8 / 6 / none, and the run's close 4 / 4 / 3 (section 1.5.2) |
| planning verbs, invocations and injections | planning held 12 / 10 / 12 main-loop requests. The `/audit:phase` body entered the main loop at every invocation, again on the second (section 1.5.3) |
| tasks serial | the second and third task ran as one wave in every session; the wave cost two requests of waiting in `whole-C-3` (requests 22 and 23) |
| a second dispatch's start | later dispatches of one agent type read 10109 (executor) and 8356 (reviewer) tokens of their start from cache (section 1.5.5) |
| gaps | the longest gap between main-loop requests was 69 / 67 / 81 seconds (the gap command, section 10) |
| the main loop's TTL | every main-loop write was at the one-hour rate (`cacheW1h` in `per stage, as billed`) |
| the two one-off requests | the cycle held 22 / 23 / 28 requests for three tasks, against six steps per task. Retries after a permission refusal recurred in every session (the results document's section 5.5) |

### 1.5 Arm C against arms A and B, decomposed

Sections 1.1 to 1.4 model one task of `feature-C-1`. The whole-feature benchmark recorded nine valid
sessions on 2026-10-07 (`<x2>`): `whole-A-1`, `whole-A-2` and `whole-A-3`; `whole-B-1`, `whole-B-3`
and `whole-B-2-r`; `whole-C-1`, `whole-C-3` and `whole-C-2-r`. The two re-runs replace the sessions
`<x2>/invalid.jsonl` names. Every arm built the feature and failed the same hidden test the same way.

**How these were read.** Each figure is printed by section 10's commands, which call the
result-reading commit's `analyse()`. Each command was run once per record. The span command was run
a second time on the three arm C records twenty seconds later and printed byte-identical output.
The records do not change, so that checks the commands, not the sessions. Each session is one
observation, and nothing here is a rate.

#### 1.5.1 The nine sessions

`python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`: the total is `all models priced`, which
equals `total_cost_usd` in every one; the requests are `contexts:` → `main` → `req`; the output pool
is `output pool, measured: main loop`; the last column is `contexts:` → `main` → `$/request`, the
price of one more main-loop request at the session's end.

| Session | Total | ÷ A's mean | ÷ B's mean | Main-loop requests | Main-loop output | One more request |
|---|---|---|---|---|---|---|
| `whole-A-1` | `0.505336` | 0.92 | 0.60 | 9 | 12166 | `0.0078` |
| `whole-A-2` | `0.600682` | 1.10 | 0.71 | 11 | 14516 | `0.0085` |
| `whole-A-3` | `0.534995` | 0.98 | 0.63 | 9 | 13074 | `0.0081` |
| `whole-B-1` | `0.764088` | 1.40 | 0.91 | 12 | 14827 | `0.0093` |
| `whole-B-3` | `1.031121` | 1.89 | 1.22 | 14 | 12108 | `0.0092` |
| `whole-B-2-r` | `0.735201` | 1.34 | 0.87 | 10 | 14199 | `0.0091` |
| `whole-C-1` | `5.068460` | 9.27 | 6.01 | 52 | 37059 | `0.0412` |
| `whole-C-3` | `5.626408` | 10.29 | 6.67 | 61 | 43211 | `0.0446` |
| `whole-C-2-r` | `5.600885` | 10.24 | 6.64 | 55 | 34707 | `0.0458` |

The ratio columns are derived: the total divided by `0.547004` and by `0.843470` (section 0.2).
Arm B's mean is 1.54 times arm A's, derived: 0.843470 / 0.547004. Arm C's mean, `5.431918`, is
9.93 times A's and 6.44 times B's, derived: (5.068460 + 5.626408 + 5.600885) / 3.

#### 1.5.2 Arm C by span

The span command (section 10) bounds each span by the verbs its requests call, as section 1.1
defines them. Planning runs from the first request that plans to the last `add` or `add-phase`
before the cycle. The billed-span command prices any run of requests: the main-loop requests, plus
every request of the agents they dispatched.

| Span | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| planning: requests | 1–12 | 1–10 | 1–12 |
| planning: main loop + agents | `1.3809` + `0` | `1.3231` + `0.2493` (explorer) | `1.4924` + `0.3219` (explorer) |
| the run's preflight and lock | 13–14: `0.2055` | 11: `0.0532` | 13–14: `0.2067` |
| **task cycle**: requests, tasks | 15–36: P1.1, P1.2, P1.3 | 12–34: the same | 15–42: the same |
| cycle: main loop | `1.5717` | `1.5157` | `1.8124` |
| cycle: executors + reviewers | `0.5219` + `0.1953` | `0.4631` + `0.1942` | `0.6025` + `0.1895` |
| cycle: the rebuild fault's row (section 1.5.7) | `−0.0134` | `−0.0115` | `−0.0142` |
| **cycle** | **`2.2755`** | **`2.1614`** | **`2.5902`** |
| **per task, and ÷ A's mean** | `0.7585`, **4.16** | `0.7205`, **3.95** | `0.8634`, **4.74** |
| sign-off: requests, cost | 45–57: `0.9637` | 35–37 and 44–48: `0.6367` | 43–52: `0.7891` |
| sign-off's fix task | 37–44: `0.5580` | 38–43: `0.3990` | none |
| the run's close | 58–61: `0.2428` | 49–52: `0.2457` | 53–55: `0.2005` |
| **phase overhead**, and ÷ A's mean | `3.3509`, 6.13 | `2.9071`, 5.31 | `3.0107`, 5.50 |

Derived: the cycle is its main loop, plus its agents, plus the fault's row. The per-task figure
is the cycle divided by three, and the ratio is the cycle divided by `0.547004`. The phase overhead
is planning, preflight, sign-off, the fix task and the close. Cycle and overhead together equal each
session's total to the fourth decimal: 2.2755 + 3.3509 = 5.6264, 2.1614 + 2.9071 = 5.0685, and
2.5902 + 3.0107 = 5.6009. The executors' and reviewers' figures are the cycle's dispatches summed
(section 1.5.5), each taken unrounded, so a split can differ in its last digit from a sum of the
rounded dispatch lines. The span command prints the cycle's agents together: `0.7172`, `0.6572` and
`0.7920`.

Read off the table:

- **The task cycle is about four times arm A or more in every session, 3.95 to 4.74.** The target
  is 2.
- **The main loop is the cycle's cost, not the agents**: 69 to 70 percent of it, derived: 1.5717 /
  2.2755, 1.5157 / 2.1614, 1.8124 / 2.5902.
- **The phase overhead costs more than the cycle**, 5.31 to 6.13 times arm A's mean on its own.

#### 1.5.3 The main loop's context, by origin

Every main-loop request reads the whole prefix written before it. The span command splits that prefix
by where each piece came from. *Command bodies* are the `/audit:*` command text, whether injected by
a `Skill` call or read with `Read`. *Main-loop output* is what the main loop itself typed: briefs,
shell commands and text.

**The prefix the cycle's first request read**, in tokens. It equals that request's `cr` (158095,
146100 and 170737 in `--json` → `requests`). In the first column a token of split rounding is
missing.

| Origin | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| reference prose | 76432 | 76455 | 76675 |
| command bodies | 38510 | 24824 | 58983 |
| session start, and what was cached before it | 20207 | 20201 | 20202 |
| other tool output (planning's code reads, `git` output, plan reads) | 10418 | 10832 | 209 |
| plugin script output | 6995 | 3909 | 2027 |
| main-loop output | 5532 | 4770 | 6790 |
| hand-backs (the explorer's, in planning) | 0 | 5109 | 4542 |
| file reads | 0 | 0 | 1309 |

**What the cycle's requests read**, in tokens and at the read rate:

| Origin | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| reference prose | 1681514, `0.3363` | 1758464, `0.3517` | 2146888, `0.4294` |
| command bodies | 847230, `0.1694` | 570953, `0.1142` | 1651524, `0.3303` |
| session start and before | 444554, `0.0889` | 464623, `0.0929` | 565656, `0.1131` |
| main-loop output | 399588, `0.0799` | 380680, `0.0761` | 513755, `0.1028` |
| plugin script output | 240058, `0.0480` | 203596, `0.0407` | 146300, `0.0293` |
| other tool output | 234917, `0.0470` | 257497, `0.0515` | 13274, `0.0027` |
| hand-backs | 97083, `0.0194` | 206252, `0.0413` | 212592, `0.0425` |
| file reads | 37399, `0.0075` | 23408, `0.0047` | 103026, `0.0206` |
| **all**, equal to the cycle's summed `cr` | 3982343, `0.7965` | 3865473, `0.7731` | 5353015, `1.0706` |

Reference prose and command bodies are 63.5, 60.3 and 71.0 percent of what the cycle read. Derived:
(1681514 + 847230) / 3982343, (1758464 + 570953) / 3865473 and (2146888 + 1651524) / 5353015. **Over
the whole session**, written once and read by every later request, the span command's last column
prices them together at 2.1896, 1.7585 and 2.3966. That is 38.9, 34.7 and 42.8 percent of the
session, derived: 1.4750 + 0.7146 of 5.6264, 1.3225 + 0.4360 of 5.0685, and 1.3812 + 1.0154 of
5.6009.

**A command body enters at every invocation.** The injection command (section 10) prints each
user text block the main loop received:

- the `/audit:phase` body came in as 42897 bytes at every invocation;
- `whole-C-3` and `whole-C-2-r` invoked it twice, once for `add` and once for the run, and the second
  time it came in again (42894 bytes) after a one-line re-invocation notice;
- `whole-C-2-r` also invoked `/audit:task add`, 75365 bytes;
- `whole-C-1` invoked `/audit:phase` once and read `commands/task.md` with `Read`.

So section 9's question about re-invocation is answered for these sessions: yes, the whole body
again. The injected text held no `${CLAUDE_PLUGIN_ROOT}`, though `phase.md` at `f7eaade4` writes it
21 times (`git show f7eaade4:plugins/audit/commands/phase.md | grep -c CLAUDE_PLUGIN_ROOT`). The CLI
the benchmark pins substitutes it in a command's body.

#### 1.5.4 Request counts, and what one request costs

The cycle's main loop, from the span command (`main requests`, `read`, `written`, `output`). Each
price column is derived: read × 0.2e-6, written × 8.0e-6 (every main-loop write was at the one-hour
rate, section 1.4), output × 20e-6. They sum to the billed main loop less its input tokens, under
`0.0004` in each session.

| | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| requests, and per task | 22, 7.3 | 23, 7.7 | 28, 9.3 |
| prefix read per request | 181016 | 168064 | 191179 |
| billed per request | `0.0714` | `0.0659` | `0.0647` |
| reads / writes / output | `0.7965` / `0.3220` / `0.4530` | `0.7731` / `0.3209` / `0.4216` | `1.0706` / `0.3539` / `0.3876` |
| output tokens: briefs, shell commands, text, other calls (estimate) | 14802, 5024, 2046, 779 | 12861, 5216, 2371, 629 | 11719, 4038, 2275, 1350 |

The output split is the output-kind command (section 10). It apportions the measured pool by the
bytes each kind emitted, as the tool does, so it is an estimate. Briefs are 60 to 65 percent of the
cycle's main-loop output, derived: 14802 / 22650, 12861 / 21078, 11719 / 19382.

Arm A's whole session made 9 to 11 main-loop requests and arm B's 10 to 14 (section 1.5.1). An arm A
request read 24245 to 26179 tokens on average (`cacheR` in `per stage, as billed` divided by `req`:
218201 / 9, 287968 / 11, 224217 / 9). The cycle's requests read 6.4 to 7.9 times as much, derived:
168064 / 26179 and 191179 / 24245.

#### 1.5.5 The agents

Per dispatch, from the span command's `dispatch` lines, whose totals include each rebuilt final:

| | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| first executor: start written, start read, cost | 18730, 0, `0.1824` | 18346, 0, `0.1890` | 18368, 0, `0.2236` |
| later executors in the cycle: start written, start read, cost | 8111 and 8147, 10109, `0.1580` and `0.1815` | 7970 and 8000, 10109, `0.1416` and `0.1325` | 7900 and 7920, 10109, `0.2154` and `0.1635` |
| first reviewer | 16404, 0, `0.0823` | 16160, 0, `0.0864` | 16155, 0, `0.0846` |
| later reviewers | 7612 and 7643, 8356, `0.0522` and `0.0608` | 7595 and 7321, 8356, `0.0496` and `0.0581` | 7461 and 7420, 8356, `0.0551` and `0.0499` |
| the project's reviewer at sign-off, on opus | 5678, 0, `0.1715` | 5515, 0, `0.1653` | 5715, 0, `0.1522` |
| the project's explorer in planning, on opus | none | 5220, 0, `0.2493` | 5555, 0, `0.3219` |

Read off the table:

- **A later dispatch shares part of its start.** Every later dispatch of an agent type read 10109
  (executor) or 8356 (reviewer) tokens from cache and wrote the rest. That answers C6c's unknown for
  these sessions: the start is shared up to a point the documentation does not name, and the part
  after it, which holds the task message, is written again.
- **The executors are the cycle's floor.** They cost 0.4631 to 0.6025 per session for the code work.
  Their listed calls (the agent-calls command, section 10, on `whole-C-3`) are skill loads, reads of
  the code, test and code writes, and test runs. The plugin's own steps, the red-first helper and
  the stamp, ride in one or two of each executor's shell calls. Which requests those steps alone
  cost is inference: they share calls with test runs.
- **The project's own agents are not the plugin's.** The organized `CLAUDE.md` both arms B and C
  carry tells the session to find helpers with the explorer and to have the reviewer check the
  diff before reporting (`<h2>/claude-md-organized.md`, working rules 1 and 5). Arm B paid the same
  agents: its reviewer `0.1104` to `0.1251`, and `whole-B-3`'s explorer `0.3234` (`python3
  tools/stream-cost.py <x2>/<session>/stream.jsonl`, `per stage, as billed`). In arm C the project's
  reviewer served as the phase review.

#### 1.5.6 The largest contributors

Ranked by what each cost across the session, with the range over the three arm C sessions:

1. **Reference prose in the main loop**: `1.3225` to `1.4750`. It was written once in planning for
   `0.6115` to `0.6134`, then read by every later request.
2. **Main-loop output**: 34707 to 43211 tokens, `0.6941` to `0.8642` at 20e-6. Briefs are its largest
   part in the cycle (section 1.5.4).
3. **Command bodies**: `0.4360` to `1.0154`, highest where the body was injected three times.
4. **The main-loop request count**: 52 to 61, against 9 to 14 in arms A and B. A cycle request cost
   `0.0647` to `0.0714`, because each read 168064 to 191179 tokens.
5. **The executors**: `0.4631` to `0.6025` in the cycle. This is the code work, and the floor.
6. **Sign-off's bookkeeping**: findings recorded and resolved one per request, `0.1253` to
   `0.4305` (the billed-span command: `whole-C-3` requests 45–46 and 48–52, `whole-C-1` 36–37,
   `whole-C-2-r` 44–47), and fix tasks for low findings, `0.3990` and `0.5580`.
7. **The per-task reviewers**: `0.1895` to `0.1953` per session.

#### 1.5.7 What the instrument gets wrong here, and where it matters

- **An injected command body is not sized.** `stream-cost.py` sizes tool results and emitted output.
  A command body arrives as a user text block, which it does not read: the `user` branch of
  `parse` sizes `tool_result` blocks and nothing else (`tools/stream-cost.py:294-305` at the
  result-reading commit). Its tokens are still counted. The request
  that writes them splits the write by bytes among the sources it does size, here the main loop's
  text and the `Skill` tool result. So `largest cache writes` shows rows of 12122 and 13799 tokens
  from 91 and 164 bytes, at 0.01 bytes per token. The totals are right and the label is wrong: the
  tool books plugin prose as the main loop's own output. Section 10's span command books a write
  as a command body when it falls at the request after a `Skill` call and holds fewer bytes than a
  tenth of its tokens. T1 fixes the tool.
- **The rebuild fault** (section 6, T1). It moves a little Sonnet cost between one model's stages and
  never out of the session. Here it matters in one place: the cycle's agent subtotal. Every dispatch
  launched in the background sits in the cycle, and every Sonnet agent of `whole-C-2-r` does too.
  So the table above nets the fault's row into the cycle. The background executors' own per-dispatch
  figures in section 1.5.5 each still hold a phantom final. The phase overhead is untouched. A
  per-task ratio would move by 0.026 at most if the row belonged elsewhere, derived: 0.0142 /
  0.547004.

### 1.6 What each phase-level step caught

Read from each arm C plan's final state (`git -C <fixture> show main:docs/audit/audit-plan.json`,
the fixture `run-meta.json` → `repo` names) and from the main loop's calls (the event command).
Costs are the billed-span command's.

| Step | Cost per session | What it caught in these sessions |
|---|---|---|
| per-task intent review | reviewers `0.1895` to `0.1953`, plus a dispatch request each (`whole-C-3`'s first: `0.1070` at request 18) | `matches` on every task. Findings in two reviews, all low: `whole-C-1` P1.1, an empty item list not refused (recorded with no fix task); `whole-C-3` P1.1, an untested refusal and an untested lower bound (fixed in sign-off by a task that added tests) |
| phase review (the project's reviewer) | `0.1522` to `0.1715`, with its dispatch `0.2364` to `0.2472` | low findings only: four in `whole-C-3`, all triaged with no change; one in `whole-C-1`, fixed (a test compared a refund with the helper's own result, not a literal); two in `whole-C-2-r`, triaged with no change |
| recording and resolving findings | `0.1253` to `0.4305` | bookkeeping. One request per finding, and a refused heredoc retried in every session |
| phase gate, then invariants | `0.1053` to `0.1066` (`whole-C-1`'s pair also resolves a finding) | passed, and no breach, in every session |
| sign-off verb, commit, landing | `0.1683` to `0.1809` | the merge itself |
| fix tasks from findings | `0.3990`, `0.5580` | tests added for low findings |

**Against the hidden tests and the grader, none of these moved anything.** Every session in every
arm ended `13/14` with the same failure (the results document's section 3), and no fix task changed
a grader flag.

**The per-task review's timing bought nothing either.** In both sessions where a per-task review
raised findings, the main loop committed that task in the request that recorded them. `whole-C-3`
request 19 calls `finding` and then `commit-task-work.py`. In `whole-C-1`, request 16 says it will
"record the finding for sign-off", then commits. So the findings were acted on at the phase, which
is where section 5 puts the review under decision G1.

**The hidden requirement every arm missed.** `RefundAmounts.test_partial_returns_add_up_exactly`
fails the same way in all nine sessions: the second of three one-unit returns refunds 2.99 where
the test wants 3.00. In arm C the refund rule was written into the plan before any code. The
per-task review answered `matches` on that task in every session, and the phase review raised
nothing about it. Every review compares the work with the plan, and the plan held the reading
every arm made. No step compares the plan with the request. So no step of today's design can catch
a misread request. Section 5.4 makes that the phase review's value test.

## 2. The yardstick: what the plugin guarantees

The plugin README sorts every rule into two tables. **Enforced:** a hook refuses before the call, or
`verify-invariants.py` refuses afterwards. **Followed:** the model is told to, in the reference prose.
Count them with
`sed -n '/^### Enforced by a hook or a script/,/^### Followed from/p' plugins/audit/README.md | grep -c '^| [^-R]'`
and
`sed -n '/^### Followed from/,/^\*\*How a row moves left/p' plugins/audit/README.md | grep -c '^| [^-I]'`.
Three rules judge every candidate below:

1. **A sentence that restates an enforced rule can go without weakening anything.** The script still
   refuses. The model meets the rule at the refusal instead of in advance, and that costs one main-loop
   request when it collides (`0.0210` at the end of `feature-C-1`).
2. **A sentence that states a followed rule can move but cannot go.** Deleting it deletes the rule,
   because nothing else holds it. It may move to a file that is read whenever the rule can apply, or
   into a script that turns it into a decision.
3. **A change that removes a subagent removes its tool list.** The README's row "the explorer cannot
   write or run a shell; the reviewer cannot edit; the executor has no web tools and no nested agents"
   is enforced by each agent's `tools:` line (`agents/audit-executor.md:4`,
   `agents/audit-reviewer.md:4`). Work that runs anywhere else is not covered by it.

**COMPATIBILITY.md, read for this design:**

- The reference prose is outside the contract (`COMPATIBILITY.md:482`), and so is every path under
  `scripts/` (`:483`). So is the shape of the evidence record (`:400`).
- A new config key or a new flag is a minor release.
- A key's default may not change behaviour for a config that does not set the key: "Absence keeps
  meaning the documented default" (`:333`). Breaking that is a major release, and `portability` is the
  precedent (`:337`).

## 3. The candidates

Each candidate follows the same order:

1. what it is;
2. the predicted saving at N = 1 and N = 5, with the arithmetic;
3. the guarantees it touches;
4. maintenance;
5. migration and COMPATIBILITY.md;
6. the benchmark reading that confirms or refutes it;
7. effort, blast radius and risk, in numbers.

C1 to C6 are the candidates the task named. C7 and C8 are what the evidence pointed to. C9 to C15
are the options the cost target named (section 0.2), priced on the whole-feature sessions. Their
whole-session arithmetic is section 5.1's, so each of them gives its figure and points there.

### C1 — A light path chosen by task risk and size

**What.** The main loop does a small, low-risk task itself. No executor is spawned and no per-task
reviewer is asked; the close records `--intent not-asked` with a computed basis. A second reading of
"light path" keeps the executor and drops the reviewer and the long brief. That reading is C5 plus C3,
and it is judged there.

**Prediction, per task, executor on opus as in `feature-C-1`:**

- removed, together `0.2691`:
  - the executor start, 16952 × 5.0 = `0.0848`;
  - its brief, 2840 × 20 = `0.0568` typed, plus `0.0225` carried by the main loop (the brief's row,
    0.01916 written and 0.00335 read);
  - its hand-back, 3125 × 20 = `0.0625` typed, plus `0.0260` carried;
  - the dispatch request itself, whose place the first inline request takes: its read of the prefix,
    82653 × 0.2 = `0.0165`.
- added: three things.
  - The executor's work, 14561 tokens (derived: 31513 − 16952), is written at the main loop's one-hour
    rate: 14561 × (8.0 − 5.0) = `0.0437`.
  - Its requests re-read the main loop's prefix instead of their own: (9 × 85269 + 44647 − 180263) ×
    0.2 = `0.1264`. 85269 is what the main loop read on its first request after the dispatch. 44647
    is the executor's reads of its own work, derived: 180263 − 8 × 16952. Every request after its
    first read the start, and the first read nothing.
  - Later main-loop requests carry the work: 14561 × 8 × 0.2 = `0.0233`.

  Together `0.1934`.
- net: `0.0757` per task.

With an executor on the sonnet row the net is `−0.1061`, a cost. The removed side shrinks to `0.1955`:
the start is 16952 × 2.5 = `0.0424` and the hand-back typed 3125 × 10 = `0.0313`, and the rest is as
above. The added side grows to `0.3016`:

- the work is written at 8.0 instead of 2.5, so 14561 × 5.5 = `0.0801`;
- the reads, `0.1264`, and the carry, `0.0233`, are unchanged;
- the work's output moves from the executor's output rate to the main loop's, twice it:
  (10306 − 3125) × (20 − 10) = `0.0718`. 10306 is the executor's output pool, less its hand-back.

Once C3 lands, the brief and hand-back rows are gone whichever path runs. The inline part then saves
the executor start and the dispatch's read, against the same additions:
0.0848 + 0.0165 − 0.1934 = `−0.0921` per task, a cost.

The per-task reviewer is skipped too, which adds C5's `0.2027`. At N = 1 that gives `0.2784` with an
opus executor and `0.0966` with a sonnet executor. The sum leaves out one interaction, worth
14561 × 0.2 = `0.0029`: the skipped dispatch would have read the inline work, not the brief and
hand-back. The revision at `9501aa91` gave `0.2781` and `0.0963`, on C5's figure before C5 counted
its moved read.

At N = 5 the square term changes too:

- Each task's main loop now makes 15 requests: eight, less the dispatch and the reviewer dispatch,
  plus nine inline.
- Each task leaves 27613 tokens in it: 21857 + 14561 − 2395 − 2764 − 3646. What leaves is the
  executor's brief and hand-back rows, and the reviewer's two together (2180 + 1466).
- That is 27613 × 0.2e-6 × 15 × 10 = `0.8284` against today's `0.3497`, a cost of `0.4787`.

So N = 5 gives 5 × 0.27844 − 0.47868 = `0.9135` with an opus executor and 5 × 0.09660 − 0.47868 =
`0.0043` with a sonnet one, both at k = 8. The revision at `9501aa91` gave `0.9118` and `0.0028`.

**Guarantees.** Rule 3: the enforced executor row does not cover light-path work. The executor's input
isolation also goes: it sees only its brief, and the main loop sees everything. The followed row "the
subagent does not commit; the orchestrator does" becomes empty. The intent check becomes `not-asked`.
The record of that stays honest, because the verb refuses the word without a basis
(`scripts/manifest/audit-task.py:7055`) and sign-off lists unanswered tasks apart from it
(`scripts/status/_status_facts.py:533`).

**Maintenance.** A second execution path, whose discipline must be restated for the main loop: test
modes, the red-first helper, the stamp. That restatement is the prose every other candidate cuts.

**COMPATIBILITY.md.** A key that turns the path on is additive while its default is off. A default of
on is a major release.

**Confirming reading.** None is scheduled, because it is not recommended. It would be an arm C session
with the key on, read inside the task cycle (section 1.1) for main-loop requests and executor
contexts per task.

**Effort, blast radius, risk.** It touches a new section of the task prose, a config key with its
schema, validator and panel control, and the README's enforced row, which would need a qualifier. It
moves one enforced row to "not covering" for the light class.

### C2 — Reference prose loaded by section on demand

**What.** Three cuts, each one decided by something other than the model's judgement:

- **by verb:** a command reads only what its verb runs;
- **by state:** a section whose condition the plan decides is read when the condition holds, named by
  the verb that knows it. Examples are an `ado` link, a retry and a high-risk task;
- **by moment:** sign-off prose is read at sign-off, not before the first task.

**Which sections a `/audit:run` of a ready, first-attempt task needs (estimate).** Each section was
sorted by the author into one of four classes:

- **keep:** always read;
- **conditional:** read when its condition holds;
- **elsewhere:** another command's, or sign-off's;
- **maintainer:** explains what a script enforces.

Bytes are per heading. `execute-task.md` is a single heading, so it was split by line ranges at
`7b489337`. Section 10 has the command.

| File | keep | conditional | elsewhere | maintainer | total |
|---|---|---|---|---|---|
| `orchestrator.md` | 30740 | 13180 | 15185 | 0 | 59105 |
| `manifest-conventions.md` | 9941 | 2268 | 9852 | 13880 | 35941 |
| `execute-task.md` | 37130 | 12319 | 0 | 9209 | 58658 |
| **sum** | **77811** | **27767** | **25037** | **23089** | **153704** |

The classes, by section:

- **keep:**
  - in `orchestrator.md`: the opening, *At a glance*, *Preflight*, *Non-negotiable guardrails*,
    *Concurrency lock*, *Progress output* and *Reporting*;
  - in `manifest-conventions.md`: the opening, locating, revalidating, the lock, status enums, areas,
    task outputs, `fileIndex`, immutable history, and the operator's words;
  - in `execute-task.md`: lines 1-383, 448-455, 484-507, 639-670, 691-701 and 713-714.
- **conditional:** readiness, which the start verb enforces; a failed run's record; ADO; trail
  lookups; dry-run; decisions; and in `execute-task.md` lines 384-447 (a widened scope, continuation,
  retry), 456-483 (the risk gate), 572-599 (a widened scope's index), 671-690 (ADO, a proof that could
  not be made) and 702-712 (the classifier).
- **elsewhere:** branch-per-phase; the third place, a red full run and quarantine; resume; id
  allocation; templates; priority; proposals; moving a task.
- **maintainer:** *Tamper evidence and completion records*; what `commit-task-work.py` enforces
  (`execute-task.md:508-571`); and the records, pathspec and `git mv` paragraphs (`:600-638`).

`tools/measure-context.py --ref 7b489337` prints 153701 bytes read first, the sum of the three
files' `read first` rows. The table's 153704 counts one more newline per file.

**Prediction.** The target is 80000 bytes read first for `/audit:run`: the keep class plus about two
kilobytes. Where a maintainer section leaves, one sentence stays: the rule and the script that
enforces it. That removes 73701 bytes, or 28023 tokens:

- N = 1: 28023 × (8.0 + 0.2 × 12) / 10^6 = `0.2914` at k = 8, and × (8.0 + 0.2 × 10) = `0.2802`
  at k = 6;
- N = 5: 28023 × (8.0 + 0.2 × 44) / 10^6 = `0.4708` at k = 8, and × (8.0 + 0.2 × 34) = `0.4147`
  at k = 6.

For the phase run form, see section 5.5.

**Guarantees.** None is weakened if two conditions hold:

- *Non-negotiable guardrails* stays in the always-read core, as R1 already said.
- Every followed row's "Stated in" names a file that is read whenever that row can apply.

The risk is a conditional file that is not read when its condition holds; its followed rule is then
silently not followed. Two things hold against it. The condition is decided by the verb that reads the
state, which prints which file applies. And a new lint checks that every followed row's anchor resolves
to a heading in a file some command reads. Reading the file the verb names stays a followed rule:
nothing checks that the model opened it.

**Maintenance.** More files. The lints and tests that name reference files must be re-pointed. Count
them with:

- `grep -rlE 'reference/(orchestrator|execute-task|manifest-conventions|phase-signoff)\.md' plugins/audit/tests | wc -l`;
- `grep -c '^def .*_drift' plugins/audit/scripts/_refs.py` (not every drift lint reads these files);
- `grep -l 'reference/' plugins/audit/commands/*.md | wc -l`.

**COMPATIBILITY.md.** None: the prose is outside the contract. It needs a CHANGELOG entry.

**Confirming reading.** In an arm C session, the tokens of the `Read <plugin>/reference/…` rows of
`largest cache writes`, summed by where T1 places the request that read them, and the run class
`$write`. Planning's reads are set beside `/audit:phase add`'s target and the run's beside the run
form's (T2). Sign-off's, after the cycle, are shown apart, because no figure here predicts them.
Summed over the whole session, the reading would set planning's and sign-off's prose against the
run's prediction: `whole-C-3` read the reference files inside planning (section 1.1).

**Effort, blast radius, risk.** 75893 bytes of prose move between files or out of the model's path
(derived: 153704 − 77811). It touches every command that names a reference file. The rows at risk are
the followed rows whose "Stated in" moves; nine cite *Execute the task*:
`sed -n '/^### Followed from/,/^\*\*How a row moves left/p' plugins/audit/README.md | grep -c 'Execute the task'`.

### C3 — A per-task spawn brief computed by a script, and the return filed by one

**What.** `audit-lookup.py brief` already computes part of the brief: which task last declared each
file, and `executor.runsGate` (`scripts/status/audit-lookup.py:274`). C3 extends it to the whole brief
that `execute-task.md` step 3 has the model compose (lines 37-202, 13353 bytes by the section 10
command). That brief holds:

- the skills, resolved area first;
- the description verbatim, the files, the docs and the desired outcome;
- the helper commands, already resolved;
- the retry context when `attempts > 1`.

The brief is written to a file and handed to the executor by path. The reviewer gets the same: the
diff, the description verbatim, the executor's return as filed, the recorded run id and the gate
commands.

Each agent files its return through a verb. The verb checks the shape the agent declares, exits 2
naming a missing field, and the agent hands back one line. A new `done --from-return` takes the
outcome, `verifiedBy`, `redFirst` and the intent answer from the filed returns.

**That means the reviewer writes.** Today it writes nothing: its prompt gives it Bash "so you can
LOOK", and lists "anything that writes" under *Must not* (`agents/audit-reviewer.md`, *What you may
run*). C3 needs the reviewer to file its own return. If the main loop filed it instead, the return
would come back into the main loop's context, which is the cost C3 exists to remove. How that one
write is held is under *Guarantees* below.

**Prediction, per task, from `feature-C-1`'s rows (`--json` → `items` and `requests`):**

| Part | Arithmetic | Saving |
|---|---|---|
| briefs no longer typed | (2840 + 2817 − 120) × 20 / 10^6; 120 tokens is the estimated cost of two short hand-off prompts | `0.1107` |
| briefs no longer carried by the main loop | 0.0192 + 0.0034 + 0.0174 + 0.0017, less 120 × 10.4 / 10^6 | `0.0405` |
| hand-backs reduced to one line in the main loop | 0.0221 + 0.0039 + 0.0117 + 0.0012, less 160 × 9.2 / 10^6 | `0.0374` |
| each agent reads its brief, one extra request each | −(14112 + 13061) × 0.2 / 10^6 | `−0.0054` |
| each agent files its return and then hands back, one extra request each, at its context's price for one more request | −(0.0063 + 0.0050), `contexts:` → `$/request` | `−0.0113` |
| the close no longer composes the outcome | (1723 + 1769 − 100) × 20 / 10^6 | `0.0678` |
| the close's tool results and text, no longer carried | 0.0158 + 0.0004 + 0.0105 + 0.0005 + 0.0133 + 0.0007 + 0.0127 + 0.0003, less 400 × 8.4 / 10^6 | `0.0508` |
| **per task** | | **`0.2905`** |

The first draft left out the filing request. Its total was `0.3019`.

The tokens a task leaves in the main loop fall from 21857 to 7178 per task. That is derived:
21857 − (2395 + 2180) − (2764 + 1466) − (1978 + 1318) − (1667 + 1591) + (120 + 160 + 300 + 100). At
N = 5 the square term shrinks with it: 5 × 0.2905 + 14679 × 0.2e-6 × 8 × 10 = `1.6874`, at k = 8.

The close's 1769 tokens came from its second attempt, which `feature-C-1` made once. Without that
attempt the per-task figure is `0.0354` lower. That attempt's two content rows go with it, a further
0.0158 + 0.0004 + 0.0127 + 0.0003 = `0.0292`.

**Guarantees.** No row of either README table is weakened, and sentences in which the task prose
admits that nothing checks something are answered:

- "Nothing checks that a returned outcome carries the block" (`execute-task.md:168`) and "Nothing
  enforces that a return carries a stamp at all" (`:249`) become the filing verb's exit code.
- "Nothing checks that a re-spawn carried any of this" (`:445`) becomes a brief whose retry context
  the script puts in.
- "Nothing compares the two for you" (`:268`) can become a script that compares the filed return with
  the recorded row.

The claim-to-task binding the reviewer exists for (`:313-315`) is kept, because the claim reaches the
reviewer verbatim from the file.

Handing the file over stays a followed rule. Nothing checks that the main loop passed the brief's path;
a PreToolUse check on the `Agent` call could, and is not proposed here. A reviewer handed anything
but its computed brief is outside the first order below, and only this followed rule covers it. Two
verbs hold the order around the filed returns, and T3 pins each with a case:

- `brief` for the reviewer exits non-zero, writing no brief, until the executor's return for the
  task's current start is filed. The reviewer's brief carries that return as filed, so it cannot be
  composed before it.
- `done --from-return` reads the executor's return for the task's current start. It also reads the
  reviewer's, unless the close passes `--intent not-asked` with its basis, which the verb already
  refuses without one (`scripts/manifest/audit-task.py:7055`). It refuses, writing nothing, when a
  return it reads is not filed for the current start, and a return from an earlier start does not
  count.

**The reviewer's one write, and what holds it.**

- *What changes.* The reviewer's prompt gains one line under *May*: one call of the filing verb.
  Its *Must not* keeps "anything that writes", with that call as the only exception.
- *What holds the write.* The verb itself, in two ways.
  - *One derived path.* It takes the task id and the role, and no path argument. From them and the
    task's current start it derives the one file it writes: that role's return for that task in the
    evidence directory. It refuses a return whose shape is incomplete without writing anything.
  - *Write-once for each task and role.* A second filing for a task and role that already has a
    return in the task's current start is refused, and the first return is left byte-identical. A
    reviewer dispatched with its computed brief finds the executor's return already filed, because
    `brief` will not compose that brief before it (above). So the reviewer's call cannot replace the
    claim it was dispatched to check, and it cannot replace its own return once that is filed.

  The start is part of the path because a retry must file again. `start` re-stamps `startedAt` on
  every start (`scripts/manifest/audit-task.py:3288`), so a re-spawned executor files beside the
  earlier attempt's return rather than over it. The attempt count would not keep two starts apart:
  the infrastructure and classifier arms set it back down (`reference/execute-task.md:699`, `:707`).

  T3 adds the cases that pin both: a path-like argument refused, a malformed return writing nothing,
  the written path equal to the derived one, and a second filing for one task and role in one start
  refused with the first unchanged. It adds a case for each of the two orders above as well.
- *What does not hold it.* `verify-invariants.py`'s `commit-scope` grades the close commit against
  the evidence directory as a whole (`commit-task-work.py` stages that directory), so it cannot tell
  the reviewer's return from any other file there.
- *What nothing checks.* Two followed rules remain:
  - **The task id and the role are the caller's word.** Nothing checks that a reviewer files as
    `reviewer`, or for the task it was handed. So a filing under a role or a task not yet filed is a
    followed rule: write-once stops a reviewer replacing a return, not filing one that nobody has
    filed yet, such as another task's or a role whose agent has not run. If a reviewer files its own
    return under the wrong task, its own task is left with none, and `done --from-return` refuses
    that close, by the case T3 pins. The only way past that refusal is a close that records
    `--intent not-asked` with its basis.
  - **The reviewer runs nothing else that writes.** That stays a followed rule, as it is today: its
    Bash can write and nothing refuses it, which its own prompt says ("Nothing refuses these"). The
    filing verb widens what the reviewer is *told* it may do by one call. It does not widen what the
    harness lets it do.
- *The enforced row is untouched.* "The reviewer cannot edit" is held by the `tools:` line
  (`agents/audit-reviewer.md:4`), and that line gains nothing: the verb runs through the Bash the
  reviewer already has.

Section 8, decision 3, asks where the file goes. Either answer leaves this write as described.

C3 also adds one single point of failure: a defect in the brief script briefs every executor wrong. The
script's selftests and the provenance it prints into each brief are what hold against that.

**Maintenance.** About 13 kilobytes of prose become one script and its selftests. The lints that pin
the brief's prose are re-pointed at the script's output. `return_shape_drift` reads `execute-task.md`
today (`scripts/_refs.py:1275`).

**COMPATIBILITY.md.** The new flags are additive. The filed return is a new record whose shape is
outside the contract.

**Confirming reading.** Each reading is taken inside the task cycle (section 1.1) and divided by the
tasks it holds.

- No cycle request's row in `largest outputs` is a `brief for audit:audit-*` above 200 tokens.
  Sign-off's reviewer brief falls after the cycle, and C3 computes no brief for it.
- The cycle's main-loop output is at most 2350 tokens per task. `feature-C-1`'s was 11374, an
  estimate (section 1.1). With C7's composite verbs, as the after-study will have them, the
  prediction for one task is 1815. That is derived:
  11374 − (2840 + 2817 − 120) − (1723 + 1769 − 100) − 630, the last term being the re-check's output.
  With C3 alone it is 2445, which is above the target.
- The task-class tokens the cycle's requests put into the main loop are at most 7400 per task.
  `feature-C-1`'s were 21857. For one task with C7, the prediction is the 5949 a task leaves
  (section 5.5). With C3 alone it is 7178.

The revision at `adece536` read both off the whole main loop less T1's planning row: targets of 5000
and 11000 against predictions of 4472 and 9547. Those readings held orient's and the run's own
output, 2657 tokens (546 + 2111, section 1.1's `out` column), and the run's own content, 3598, which
no task pays. In an arm C session they also held sign-off's, which neither prediction counted. Each
target moves by what the cycle leaves out of `feature-C-1`: 5000 − 2657 = 2343, rounded to 2350, and
11000 − 3598 = 7402, rounded to 7400. So each keeps its place against the two predictions.

**Effort, blast radius, risk.** It touches one extended script, a new verb and flag in
`audit-task.py`, both agent prompts, the task prose, `_refs.py`, and `PLUGIN-BUILD-GUIDE.md`. The
enforced and followed tables lose no row, and the admissions that nothing checks a return's shape or
its stamp are answered by an exit code. The reviewer's prompt loosens by one call, held as above.

### C4 — Rules a script already enforces, deleted from the prose

**What.** A sentence stays when it tells the model what to do. A paragraph that explains what a script
does for the model moves to `PLUGIN-BUILD-GUIDE.md` or to the script's docstring. One sentence is left
in its place: the rule, and the script that enforces it. The scope is the maintainer class of C2's
table, 23089 bytes.

**Prediction.** 8779 tokens, from the section 1.2 prose formula: `0.0913` at N = 1 and `0.1475` at
N = 5 at k = 8, and `0.0878` and `0.1299` at k = 6. This is part of C2's cut, not an addition to it.
The agents' own prompts qualify too, but at section 1.3's prices a kilobyte there is worth `0.00251`
per executor dispatch, against `0.00380` to `0.00639` for the same kilobyte in the main loop.

**Guarantees.** None, by construction: only restatements of enforced rows go. Rule 2 keeps the followed
column out of scope. Three lints pin sentences in these files so that the prose agrees with the code:
`runner_list_drift`, `red_first_drift` and `return_shape_drift`. Where a pinned sentence moves, its
lint moves with it.

**Maintenance.** Lower than today. A refusal's own text already carries the remedy at run time, and
the explanation lives once, beside the code.

**COMPATIBILITY.md.** None.

**Confirming reading.** The same as C2.

**Effort, blast radius, risk.** 23089 bytes move, all inside C2's edit. No row of either table
changes.

### C5 — The reviewer gated by risk

**What.** R8's `review.perTask`, re-priced. The per-task intent call is skipped for tasks the gate
deems safe.

**Prediction, per skipped task, today:**

- the reviewer stage as billed, `0.0957`;
- its brief, 2817 × 20 = `0.0563`;
- the brief carried by the main loop, `0.0192` (0.01744 written and 0.00174 read);
- its hand-back carried, `0.0129`;
- the dispatch request's read of the prefix, 91886 × 0.2 = `0.0184`;
- one read that moves. The dispatch is the request that writes the re-check's 1229 tokens, so
  without it the commit writes them instead of reading them: 1229 × 0.2 = `0.0002`.

That is `0.2027`. The revision at `9501aa91` gave `0.2024`: it left out the moved read, and it
summed the brief's carry from rounded parts. With every task skipped at N = 5 and k = 8, the square
term shrinks two ways. Each task leaves 3646 fewer tokens (21857 → 18211), and each later task makes
one request fewer (8 → 7). The prediction is 5 × 0.202696 + (8 × 21857 − 7 × 18211) × 0.2e-6 × 10 =
`1.1082`. The first draft counted only the first of the two, as `1.0704`, and the revision at
`9501aa91` gave `1.1068`.

After C3 and C7 the brief and the hand-back shrink to section 5.5's 140 tokens, and the reviewer
makes C3's two extra requests. Skipping it then saves `0.1153` per task, derived:

- the reviewer stage as billed, 0.09565;
- C3's two extra reviewer requests, 13061 × 0.2 / 10^6 + 0.0050 = 0.00761 (C3's table);
- the 60-token hand-off, typed: 60 × 20 / 10^6 = 0.00120;
- the dispatch's 140 tokens, written and read by the two requests after it:
  140 × (8.0 + 0.2 × 2) / 10^6 = 0.00118;
- the dispatch request's read, 47003 × 0.2 / 10^6 = 0.00940. 47003 is what that request would read
  in section 5.5's model: 41055 run tokens, the 3192 of the run's own requests, and 2756 of the task's
  own written before it (2616 + 140);
- the read that moves: the commit writes the gate's 1458 tokens instead of reading them,
  1458 × 0.2 / 10^6 = 0.00029.

The revision at `9501aa91` gave `0.1051`, from the stage and the dispatch's read alone.

**Guarantees.** The per-task claim-to-task binding (`execute-task.md:313-315`) becomes conditional.
The record stays honest: `not-asked` needs a basis, and sign-off lists unanswered tasks. One
structural weakness stands: `task.risk` is written by whoever plans the task. In the whole-feature
benchmark that is the session whose work would be reviewed, so the subject chooses its own review.

R8's `risky` arm does not avoid that (`token-efficiency-audit.md:644-646`). It runs the review in
three cases:

- `task.risk` is `med` or `high`, the same self-declared field;
- a `tdd` task's `redFirst` did not come back `proved`;
- the gate's row disagrees with the executor's return.

The last two are computed, and C3 is what makes the third computable by a script. A gate on those
two alone is narrower than R8, and it is option (b) in section 8.

**Maintenance.** A config key with its schema, validator, panel control and doctor line.

**COMPATIBILITY.md.** The key is additive with a default of `always`. A gated default is a major
release.

**Confirming reading.** The `audit:audit-reviewer` dispatches inside the task cycle (section 1.1),
set against the tasks it holds. Sign-off's reviewer is dispatched after the cycle, so it is not
counted. For quality, R8's section 7.5 count: tasks where `always` returned `diverges` or
`cannot-tell` that the gate would have skipped.

**Effort, blast radius, risk.** It touches a config key, the reviewer step's prose and the panel. It
narrows one followed check, and it is the user's decision (section 8).

### C6 — A layout that keeps the prompt cache warm across stages

Four layouts, judged apart:

- **a. The main loop's TTL.** The analysis derived `0.2791` for `feature-C-1` if every main-loop write
  were at the five-minute rate: 93025 tokens × 3.0 / 10^6. At N = 5 the main loop writes 180453
  tokens at k = 8. That is derived: 9922 + 57648 + 3598 + 5 × 21857, the orient writes, the prose
  request's write, the run's own requests' content and five tasks' content. The prediction is
  180453 × 3.0 / 10^6 = `0.5414`, if no gap ever passes five minutes. At k = 6 the figures are
  `0.2647` at N = 1 and `0.4694` at N = 5, on (71168 + 17059) and (71168 + 5 × 17059) tokens.
  One lapse at the start of the fifth task re-writes the prefix, 79461 + 3192 + 4 × 21857 = 170081
  tokens: 170081 × 5.0 / 10^6 = `0.8504`, against `0.0340` to read it. Which TTL a user's main loop
  gets, and whether a plugin can set it, are both **unknown** to the plugin (section 9). This is the
  user's setting and the user's bet on their gaps; it is not a plugin change.
- **b. A fork for the reviewer.** A fork's first request reads the parent's cache, so the reviewer's
  start is not written. But every fork request reads the whole main prefix on the parent's model, its
  output is priced on opus, and what it writes is written at opus's five-minute rate. Against the
  reviewer stage as billed, `0.0957`, a fork costs `0.17864` (derived):
  - reads: (4 × 93115 + 13847) × 0.2 / 10^6 = `0.07726`. 93115 is the parent's prefix at the dispatch
    (91886 read plus 1229 written). 13847 is the reviewer's reads of its own work, 61481 − 3 × 15878.
  - output: 2080 × 20 / 10^6 = `0.04160`.
  - writes: the directive the fork receives, as long as the brief, plus the reviewer's work,
    (2817 + 9139) × 5.0 / 10^6 = `0.05978`. 9139 is 25017 − 15878.

  The prediction is 0.0957 − 0.1786 = `−0.0829` per task: it costs more. The first draft gave
  `−0.0653` with no arithmetic. A fork also "sees the same system prompt, tools, model" as the parent
  (host facts), so the enforced row "the reviewer cannot edit" goes, along with
  `phase.review.model` and the reviewer's input isolation. **Rejected.**
- **c. Agent starts shared across dispatches.** In both recorded plugin sessions each agent's first
  request read nothing from cache: `start_cR` 0 under `contexts:` for `feature-C-1` and the pilot.
  Whether a second dispatch of one agent type reads the first one's prefix is unmeasured. It depends on
  the order of a subagent's initial context, which the docs list but do not order (**unknown**). The
  upper bound per later dispatch is 14112 × 4.8 / 10^6 = `0.0677` for the executor and 13061 × 2.3 /
  10^6 = `0.0300` for the reviewer, `0.3911` at N = 5. This is a property of the host and nothing to
  build. If sharing stops at the task message, C3's short briefs are already the lever.
  `experimental.cacheTtl` on the agents is R7, unchanged. The executor's requests were seconds apart in
  `feature-C-1`, 9 requests in 82.2 s (`per stage, as billed`, `req` and `wall_s`).
- **d. Reading at the point of use.** This is C2's "by moment".

**Guarantees.** (a) and (c) touch none. (b) drops an enforced row.

**COMPATIBILITY.md.** None.

**Confirming reading.** The main loop's longest gap and each later dispatch's `start_cR`, from the
whole-feature sessions. Today's tool prints neither; T1 adds both.

### C7 — Fewer main-loop round trips per task (pointed to by the evidence)

**What.** In `feature-C-1` the task took eight main-loop requests, six steps and two one-offs
(section 1.1). Composite verbs fold them into five:

1. start, plus the brief;
2. dispatch;
3. the recorded gate, the stamp comparison and the reviewer brief;
4. dispatch the reviewer;
5. the commit, plus `done --from-return`.

Each composite calls the existing verbs in the existing order, stops at the first refusal, and prints
it.

**Why the evidence points here.** A main-loop request costs `0.0210` against the executor's `0.0063`
(`contexts:`). The main loop is the dearest place in the pipeline to spend a round trip.

**Prediction.** It depends on the per-task shape more than any other candidate's does.

- **At k = 8**, as `feature-C-1` recorded it, three requests go: the re-check (`yyXaVM`) and both
  close attempts. The saving is `0.0807` per task, from four parts:
  - their reads, (90428 + 96761 + 97956) × 0.2 / 10^6 = `0.0570`. Of that, 0.0477 is run tokens
    (3 × 79461), 0.0019 is the run's own requests' content (3 × 3192), and 0.0074 is per-task
    content;
  - the re-check's output, 630 × 20 / 10^6 = `0.0126`;
  - the re-check's content, written by the next request and read by the three that remain:
    0.00983 + 1229 × 3 × 0.2 / 10^6 = `0.0106`;
  - two reads that move, because a row enters the cache at the request after the one that made it.
    With the re-check gone, the reviewer dispatch writes the gate's 1458 tokens instead of reading
    them. With both closes gone, the lock release writes the commit's 1195.
    (1458 + 1195) × 0.2 / 10^6 = `0.0005`.

  The outcome the close composes, and the retry's output and content, are counted in C3, not here.
  At N = 5 each task also leaves 1229 fewer tokens and makes 5 requests instead of 8:
  5 × 0.08075 + (8 × 21857 − 5 × 20628) × 0.2e-6 × 10 = `0.5472`. The revision at `9501aa91` gave
  `0.0802` and `0.5444`, without the moved reads.
- **At k = 6** only the close folds into the commit, so one request goes. Its read is
  (96761 − 1229) × 0.2 / 10^6 = `0.0191`. One read moves: the lock release writes the commit's 1195
  tokens instead of reading them, `0.0002`. Together, (95532 + 1195) × 0.2 / 10^6 = `0.0193` per
  task. At N = 5: 5 × 96727 × 0.2e-6 + 17059 × 0.2e-6 × (6 − 5) × 10 = `0.1308`. The revision at
  `9501aa91` gave `0.0191` and `0.1296`.

Whether C7 removes the two one-offs at all is inference:

- The retry came from a shell-built argument list, and a composite verb takes none.
- The re-check goes away only if the composite prints which field of a stale stamp moved, so the
  model has nothing left to look up.

The first draft gave `0.0795`. It included a `0.0099` for the re-check's rows that it did not
derive, and its N = 5 term left out the smaller content. In wall clock, the main loop's stages took
119.0 s over 15 requests (derived from `wall_s`: 6.2 + 37.3 + 31.4 + 44.1). So three fewer requests
is about 24 s per task at k = 8, and one fewer is about 8 s at k = 6. That is a crude prediction: a
request's wall includes the gate run it starts.

**Guarantees.** None weakened. The per-task order becomes a verb's order rather than a paragraph's.

**COMPATIBILITY.md.** New verbs are additive.

**Confirming reading.** The task cycle's main-loop requests (section 1.1), divided by the tasks it
holds: at most 5. `feature-C-1`'s cycle is requests 6 to 13, so it reads 8 for its one task, two of
them one-offs. Nothing is subtracted, because the cycle holds no request of orient, planning, the
run's own or sign-off. The revision at `adece536` read the same figure off `per stage, as billed`,
as the plan, gate and close requests before sign-off less the run's own five, with T1's planning
row apart: (5 + 3 + 5 − 5) / 1 = 8.

**Effort, blast radius, risk.** It touches `audit-task.py`, plus the existing governance scripts it
calls but does not re-implement. No row of either table changes.

### C8 — Verb-scoped command reads (pointed to by the evidence)

**What.** `/audit:phase` tells the model to read all four reference files before it chooses its verb
(`commands/phase.md:9-13`). So `/audit:phase add`, a structural write, loads 242068 bytes:
`python3 tools/measure-context.py --ref 7b489337`, the `/audit:phase` total. `/audit:task` reads
`manifest-conventions.md` first (`commands/task.md:51`), and its body carries every one of its verbs.
Measured the same way, a command body without its frontmatter plus the files it reads first, it
loads 108170 bytes (72230 + 35940). The tool has no `/audit:task` entry yet (T1 adds one), so
section 10 gives the command that asks its rule directly.

C8 makes the verb choice first and the read second. Each verb's prose goes in a file the dispatcher
names, which is the supporting-file pattern the skills documentation describes. Injecting the verb's
section through `!` command substitution would save the extra read, but it depends on a substitution
the docs do not state (section 9).

**Prediction, per invocation.** The targets are 30000 bytes for `/audit:phase add`, which needs its own
section and the conventions it writes against, and 45000 for `/audit:task add`.

| Invocation | Tokens removed | Carried by 20 later requests | Carried by 50 |
|---|---|---|---|
| `/audit:phase add` | 80634, derived: (242068 − 30000) / 2.63 | `0.9676` | `1.4514` |
| `/audit:task add` | 24019, derived: (108170 − 45000) / 2.63 | `0.2882` | `0.4323` |

Both rows price a token at its write plus its reads: 8.0 + 0.2 × 20 = 12.0, and 8.0 + 0.2 × 50 =
18.0, per million.

At N = 1 in the `/audit:run` shape the saving is zero, because that command plans nothing. In the
whole-feature benchmark's arm C, C8 is where the session may differ most from `feature-C-1`. A dollar
figure for arm C's planning is not predicted, because it needs the invocation count.

**Guarantees.** None. The verb dispatch is already lexical (`commands/phase.md`, *0. Which verb*).

**COMPATIBILITY.md.** None: the command names stay.

**Confirming reading.** The plugin command-body injections and reference reads per session. Today's
tool does not count them; T1 adds the count.

### C9 — A step driver: a script runs the pipeline, the model writes code and answers named decisions

**What.** One entry point, `drive-phase.py next <phase>`, reads the plan and the filed returns. It
performs every step that is due and needs no judgement, then prints exactly one instruction. Those
steps are:

- the preflight and the lock;
- `start`, and the computed brief (C3);
- the recorded gate and the stamp comparison;
- the commit and `done --from-return`;
- at sign-off, the phase gate, the invariants check, the sign-off verb, the landing and the lock
  release.

The instruction is one of three things:

- **dispatch**: an agent type and a brief path, or several for a wave;
- **decide**: a named decision with its options, such as a finding's triage or a red-first that
  could not be proved;
- **done**.

A refusal prints the refusal with its remedy and stops. The command body is the loop: run `next`,
do what it prints, run `next` again. So per task the main loop makes four requests: dispatch the
executor, `next` (gate and stamp, then the reviewer's brief), dispatch the reviewer, `next` (commit,
close, and the next task's dispatch). C7's composite verbs become the driver's steps.

**Why the evidence points here.** The cycle's main loop is 69 to 70 percent of the cycle, and it made
7.3 to 9.3 requests per task, each reading 168064 to 191179 tokens (sections 1.5.2 and 1.5.4). Most of
what those requests did was a script's job: run a verb, read its output, type the next command.
Briefs alone were 60 to 65 percent of their output.

**Prediction.** With C2, C3 and C10, which are its parts, the cycle's main loop falls from
`1.5717`, `1.5157` and `1.8124` to `0.2137`, `0.2262` and `0.2036` (section 5.1, rung 1). Taken in
the order they would land, removing the prose saves `0.4859`, `0.4452` and `0.7345`. The driver with
its computed briefs and terse output then saves `0.8555`, `0.8314` and `0.8790` (section 5.1's
attribution).

**Guarantees.** None is weakened:

- Every step it performs is an existing verb, called in the existing order.
- The recorded gate stays before the reviewer's dispatch, so the reviewer still receives the
  recorded run. That is why a task takes four requests, not three.
- Each followed rule is printed at the step it applies to, or stated in the agent prompt that acts
  on it. T2's anchor lint holds that every followed row of the README resolves to one of the two.
- A judgement the model made silently becomes a named decision with its options printed.

**Maintenance.** One entry point with its tests. The command bodies shrink to the loop. The
composite verbs C7 would have added are its steps instead.

**COMPATIBILITY.md.** A new script under `scripts/`, outside the contract. The commands keep their
names.

**Micro-test.** Offline (T4): a drive over a fixture plan of three tasks with filed returns, which
prints the instruction sequence. That sequence is four model-facing steps per task, each success
print at most 300 bytes. A stale stamp prints which field moved, which removes `feature-C-1`'s
re-check request.

**Effort, blast radius, risk.** A new entry point, the bodies of `/audit:phase`, `/audit:run`,
`/audit:next` and `/audit:resume`, and T1's cycle rule, which must read the driver's own `start` and
`done`. The risk is a single point of failure: a defect in the driver misdrives every run. Its
selftests and the existing verbs' own refusals hold against it.

### C10 — Terse plugin script output by default

**What.** Every verb the driver or the main loop calls prints one line on success, and its refusal
in full. `--verbose` keeps today's text.

**Prediction.** Plugin script output in the main loop cost `0.1705` to `0.3091` per session, written
and carried (section 1.5.3). Under the driver most of it never reaches the main loop. What still
did at the cycle's start was 2027 to 6995 tokens. One line in place of today's text removes nine
tenths of it, an estimate: `0.0051` to `0.0176` in the cycle (section 5.1). Terse output is also what
holds the driver's per-task write at the 1000 tokens rung 1 assumes.

**Guarantees.** None. A refusal and its remedy still print in full.

**Micro-test.** Offline (T7): each verb's success path, run on its selftest fixture, prints one line
of at most 200 bytes without `--verbose`.

### C11 — One executor per phase instead of one per task

**What.** One executor runs every task of the phase in turn, each brief arriving as a further message.

**Prediction, on `whole-C-3`: a cost of about `0.047`.**

- *Added.* Each later task's requests read the earlier tasks' work. That work is each executor's held
  context less its start (`contexts:`, `task` + `file` less `start_cR` + `start_cW`): 31922 − 18730
  = 13192 for P1.1, and 34729 − 18220 = 16509 for the wave's first executor. Serially, the second
  task's 9 requests read 13192 more each, and the third task's 10 requests read 13192 + 16509 more
  each:
  (9 × 13192 + 10 × 29701) × 0.2e-6 = `0.0832`.
- *Saved.* Two later starts, less their briefs, which are written either way:
  (8111 + 8147 − (4253 + 4463) / 2.63) × 2.5e-6 = `0.0324`, plus their first reads,
  2 × 10109 × 0.2e-6 = `0.0040`.
- *Net.* 0.0832 − 0.0364 = `0.0468` more.

**Guarantees.** It gives up per-task input isolation: each task's executor would see the earlier
tasks' work. It also gives up the parallel wave every session ran.

**Rejected.** It costs more and gives up two guarantees.

### C12 — Fewer and cheaper main-loop requests

**Fewer.** The driver makes a task four requests (C9). The planning batch verb makes planning's
writes one call (T9). The sign-off step makes sign-off a review, a decision and a final step (T10).
Together they take the session from 52 to 61 main-loop requests to 23 in rung 1's model, and 26
with one fix task: 5 planning + 14 cycle + 4 sign-off, + 3 per fix task.

**Cheaper.** A smaller prefix (C2, C8) and less output (C3) make each request cheaper. The model is
the other lever: a `model:` line on the run command would put the loop on a cheaper model. Per the
host facts, that switch makes the next request re-read the whole history with no cache hit. At
rung 1 that re-write costs 41358 × 4.0e-6 = `0.1654` in `whole-C-3`, against `0.047` saved on the
cycle's writes and output: 3000 × 4.0e-6 + 3500 × 10e-6. **Rejected: a cost of about `0.12`.**
Whether a smaller model answers the named decisions as well is unmeasured.

### C13 — A smaller subagent start

Each lever of the host facts, priced on the whole-feature sessions:

- **`omitClaudeMd`.** The fixture's `CLAUDE.md` is 2193 bytes, about 834 tokens (231 + 1962 bytes,
  `wc -c <h2>/claude-md-base.md <h2>/claude-md-organized.md`; results document section 3.1). Per
  executor dispatch it would save about 834 × (2.5e-6 + 0.2e-6 × 8) = `0.0034`, about `0.02` per
  session. Its organized part is the rules arm A lacked and broke, and arms B and C kept (the
  results document's section 4.3). **Rejected on value**: it would pay for two cents with the one
  quality difference the benchmark measured.
- **Preloaded skills** (`skills:`). The executors loaded the task's skills with the `Skill` tool in
  their first request, beside their first reads (the agent-calls command). Preloading writes the same
  content in the start and saves no request. A plugin agent cannot know a project's skills either.
  **Neutral; not taken.**
- **`experimental.cacheTtl: 1h`.** Agents' requests are seconds apart, so a longer cache bridges
  nothing. It raises the agents' write rate from 2.5 to 4.0: on `whole-C-3`'s agent writes,
  (94531 + 65213) × 1.5e-6 = `0.2396` more (`per stage, as billed`, `cacheW5m` of `executor` and
  `reviewer`). **Rejected.**
- **Trimmed agent prompts** (T8). `audit-executor.md` from 18790 bytes to 9000 and
  `audit-reviewer.md` from 15689 to 7000, both targets estimates. What leaves is procedure a script
  can run (C3's filing, red-first, the stamp) and explanation of what scripts enforce (C4's rule). The
  cut is priced as written once and read by every request of that agent type in the session:
  (18790 − 9000) / 2.63 × (2.5e-6 + 0.2e-6 × n_e) + (15689 − 7000) / 2.63 × (2.5e-6 + 0.2e-6 × n_r),
  where n_e and n_r are the executors' and reviewers' requests in the cycle. That is 26 and 9, 23 and
  9, 32 and 8, giving `0.0429`, `0.0406` and `0.0467`. **Taken.** C3's extra agent requests, one to
  read the brief and one to file the return, add `0.0654` per session: 3 tasks × 2 × (0.0067 +
  0.0042), the executor's and reviewer's `$/request` in `whole-C-3`'s `contexts:`. So the agents' net
  under rung 1 is `+0.0187` to `+0.0248`.
- **Measured, not a lever.** A later dispatch already reads 10109 or 8356 tokens of its start from
  cache (section 1.5.5).

### C14 — The per-task review: cheaper, gated, or moved to the phase

- **Cheaper, with no guarantee change.** The reviewer already runs on Sonnet, at `0.0496` to `0.0864`
  per review (section 1.5.5). The main loop's share is the dearer part: typing a 2771- to 3942-token
  brief (`whole-C-3`'s `largest outputs`), then carrying it and the hand-back. C3 and C9 remove that
  share. Rung 1 includes it.
- **Gated on computed signals (G2).** This is C5's option (b). The review runs when the task's
  `redFirst` did not come back `proved`, or when the gate row disagrees with the executor's filed
  return. In these sessions the first signal fired once per session, on the command-line task (the
  results document's section 4.4). So one review ran where three did. Saving: `0.1981` to `0.2073`
  per session over rung 1 (section 5.1).
- **Moved to the phase (G1).** The phase review reads every task's filed return against its
  description, and no reviewer runs per task. Saving: `0.2887` to `0.3024` per session over rung 1.
  The phase review gains three returns to read: 3 × 1500 × (5.0e-6 + 0.2e-6 × 4) = `0.0261`, an
  estimate of 1500 tokens a return, on the project's opus reviewer.

Section 5.1 gives both as rungs, with the guarantee each changes and how it is held instead.
Section 1.6 gives the evidence about value: the per-task reviews raised low findings on P1.1 in
`whole-C-1` and in `whole-C-3`, on no other task (read from the main loop's calls), and both were
acted on at the phase.

### C15 — An enforced rule moved from an agent's tool list to a hook

The README's enforced row "the reviewer cannot edit; the executor has no web tools and no nested
agents" is held by each agent's `tools:` line (section 2, rule 3). Two candidates would remove an
agent, and with it that line. A `PreToolUse` hook could hold the rule instead. It would deny
`Edit`/`Write` for the length of a review, or `WebFetch`, `WebSearch` and `Agent` for the length of
an inline task, keyed on a marker the driver sets and clears. The hook keeps the rule enforced. It
does not keep input isolation, which no hook can give. Re-priced at rung 1's prefix:

- **The light path (C1)**, the main loop doing the task, costs about `1.00` against rung 1's `0.9400`
  in `whole-C-3`. This is an estimate:
  - A's mean work, `0.547004`;
  - the larger prefix it reads, about 3.3 requests a task (A's 9 to 11 over three tasks) × [3 ×
    (41358 − 16607) + 15000 × (0 + 1 + 2)] × 0.2e-6 = `0.0787`. Here 16607 is `whole-A-1`'s first
    read and write (11891 + 4716), and 15000 is an estimate of the work a task leaves;
  - the driver's requests without the executor's dispatch, 11 of them:
    0.2e-6 × (11 × 41358 + 3000 × 5) + 3000 × 8.0e-6 + 2750 × 20e-6 = `0.1730`;
  - the reviewers, `0.2063`.

  The executors run on Sonnet and the main loop on Opus, so the work costs more inline.
- **A forked reviewer (C6b)** reads the main prefix on Opus: 3 × 45358 × 0.2e-6 + 9000 × 5.0e-6 +
  2000 × 20e-6 = `0.1122` per review, against a Sonnet review at about `0.065`. It costs `0.047` more
  per task.

**Neither pays, so no rule moves to a hook.** This is recorded so the option is not reopened without
a new price.

### Considered and set aside

- **A fresh main loop per task.** This trades the square term for paying, per task, what a run pays
  once. After the recommended change, that is `0.3263` (derived):
  - the run write once the prose is cut, `0.2333`;
  - its output, `0.0109`;
  - the early reads, `0.0110`;
  - the run's own requests' work, `0.0711`.

  The square term is 5949 × 0.2e-6 × 5 × N(N−1)/2 (section 5.5), so break-even is at about 110
  tasks: 2 × 0.3263 / (5949 × 0.2e-6 × 5). Below that, one main loop is cheaper. The first draft
  counted the run write alone, against a larger per-task content, and put break-even near 45.
- **A cheaper model for the main loop**, through a command's `model:` frontmatter. The main loop holds
  every followed rule. And per the host facts, a model switch mid-session re-reads the whole history
  with no cache hit. The model is the user's choice, not a cost lever this design takes. C12 prices
  it at rung 1: a cost of about `0.12` in `whole-C-3`.
- **`omitClaudeMd`.** This is R5, unchanged. The executor needs the project's `CLAUDE.md`, as R5
  already said. C13 prices it on the whole-feature fixture: about `0.02` a session, against the rules
  that separated arm A from arms B and C.

## 4. Side by side

All savings are predictions in USD, from section 1's model, at k = 8, the per-task shape
`feature-C-1` recorded. A figure in brackets is the same prediction at k = 6, where the candidate's
own section gives one. "Rows" means rows of the README's enforced and followed tables.

| | N = 1 | N = 5 | Guarantees | Maintenance | COMPATIBILITY.md | Verdict |
|---|---|---|---|---|---|---|
| C1 light path, executor on opus / on sonnet | `0.2784` / `0.0966` | `0.9135` / `0.0043` | an enforced row stops covering the work; isolation lost | a second execution path | key additive; default on is major | not recommended |
| C2 by verb, state and moment | `0.2914` (`0.2802`) | `0.4708` (`0.4147`) | none, if every followed row stays reachable | more files; lints re-pointed | none | **recommended** |
| C3 computed brief, filed return | `0.2905` | `1.6874` | no row of either table; a return's shape and stamp become checked; the reviewer gains one write, through a write-once filing verb that derives its one path and never replaces a return already filed; the task id and role it files under are the caller's word | prose becomes a tested script | additive | **recommended** |
| C4 enforced restatements out | `0.0913` (`0.0878`) | `0.1475` (`0.1299`) | none, by construction | lower | none | **recommended**, inside C2 |
| C5 reviewer by risk | `0.2027` per skipped task | `1.1082` if every task skips | one followed check narrowed | a config key | key additive; gated default is major | the user's, as G2 (section 8) |
| C6a main-loop TTL | `0.2791` (`0.2647`) | `0.5414` (`0.4694`) | none | none | none | the user's setting; the gaps were measured under five minutes (section 1.4) |
| C6b fork reviewer | `−0.0829` per task | | an enforced row lost | | | rejected |
| C6c shared agent starts | `0` | up to `0.3911` | none | none | none | measured: a later dispatch shares part of its start (section 1.5.5); nothing to build |
| C7 five requests per task | `0.0807` (`0.0193`) | `0.5472` (`0.1308`) | none | composite verbs | additive | superseded by C9's four |
| C8 verb-scoped command reads | `0` | per invocation, section 3 | none | dispatcher plus verb files | none | **recommended**, inside C9 |

The rows do not add up. C3 shrinks what C7's removed requests would have read, and C2 shrinks the
prefix every request reads. Section 5.5 computes the earlier set once, together.

**The candidates the cost target named, on the whole-feature sessions.** Savings are per session,
across `whole-C-3`, `whole-C-1` and `whole-C-2-r` in that order of range, from section 5.1's model.

| | Saving per session | Guarantees | Verdict |
|---|---|---|---|
| C9 step driver, with C2, C3, C8 and C10 as its parts | cycle main loop `1.5157`–`1.8124` → `0.2036`–`0.2262` | none | **recommended** (rung 1) |
| C10 terse output | `0.0051`–`0.0176` in the cycle after C9; it holds C9's per-task write | none | **recommended**, inside C9 |
| C11 one executor per phase | `−0.0468` (a cost, `whole-C-3`) | per-task isolation and the parallel wave lost | rejected |
| C12 cheaper main-loop model | about `−0.12` (a cost, `whole-C-3`) | unmeasured decision quality | rejected |
| C13 trimmed agent prompts | `0.0406`–`0.0467` | none | **recommended** (rung 1) |
| C13 `omitClaudeMd` / skills / agent TTL 1h | about `0.02` / `0` / `−0.2396` | the project's rules / none / none | rejected / not taken / rejected |
| C14 per-task review gated (G2) | `0.1981`–`0.2073` over rung 1 | the intent check becomes conditional | the user's (section 8) |
| C14 per-task review at the phase (G1) | `0.2887`–`0.3024` over rung 1 | the intent check moves from before each commit to before the merge | the user's (section 8) |
| C15 light path or fork reviewer, with a hook holding the tool rule | about `−0.065` a session / `−0.047` a task (costs) | input isolation lost | rejected |

## 5. Recommendation: the ladder to the cost target

### 5.1 The ladder

**The model.** A main-loop span of `k` requests that starts at a prefix of `P` tokens, writes `W`
tokens over the span and emits `O` output tokens costs

`main(k, P, W, O) = r × (k × P + W × (k − 1) / 2) + w × W + o × O`

with section 1.2's rates, `r` = 0.2e-6, `w` = 8.0e-6 and `o` = 20e-6 (every main-loop write here was
one-hour). The middle term spreads `W` evenly over the span. On today's cycles, with section 1.5.4's
readings, it gives:

- `main(22, 158095, 40254, 22650)` = `1.5552`, against the billed `1.5717`;
- `main(23, 146100, 40110, 21078)` = `1.5027`, against `1.5157`;
- `main(28, 170737, 44238, 19382)` = `1.8171`, against `1.8124`.

So the model is within 1.1 percent of each.

**Rung 0, today**, is measured (section 1.5.2).

**Rung 1 weakens no row of the README's two tables.** The reviewer gains one filing write, held as C3
says, and section 5.2 shows how each guarantee is held. It is C9 with its parts: C2, C3, C4, C8 and
C10, the agent half of C13, the planning batch (T9) and sign-off as one step (T10). Its inputs, each
labelled:

- **The prefix the cycle starts at**, `P′` = `P` − reference prose − command bodies − 0.9 × plugin
  script output + 4500 (section 1.5.3's readings):
  - `whole-C-3`: 158095 − 76432 − 38510 − 0.9 × 6995 + 4500 = `41358`;
  - `whole-C-1`: 146100 − 76455 − 24824 − 0.9 × 3909 + 4500 = `45803`;
  - `whole-C-2-r`: 170737 − 76675 − 58983 − 0.9 × 2027 + 4500 = `37755`.

  The 4500 tokens are the thin bodies, an estimate: a run form of at most 4000 bytes and an add form
  of at most 8000, divided by 2.63 (T2's ceilings). The 0.9 is what terse output removes, also an
  estimate (C10).
- **Requests**, `k` = 4 per task + 2 = 14. Four per task is C9's shape, and the 2 are the wave's two
  waiting requests as `whole-C-3` recorded them (requests 22 and 23). That is an estimate: a serial
  run would have no waits.
- **Writes**, 1000 tokens a task, so `W` = 3000. These are two dispatch calls, two one-line
  hand-backs, two terse `next` prints and the model's text, an estimate.
- **Output**, 250 tokens a request, so `O` = 3500. The run's own preflight requests, each one short
  script call, emitted 242 tokens on average, derived: (415 + 477 + 318) / 5, the span command's
  `pre` rows.
- **Agents**: today's cycle agents, net of the fault's row, plus C3's extra requests (`0.0654`) less
  the prompt trims (`0.0429`, `0.0406`, `0.0467`), from C13.
- **Planning** writes everything the cycle then reads, `P′` less what was cached before the session,
  at `w`. Its five requests (an estimate: invoke, read the code over two requests, write the plan
  file, one batch `add`) read halfway between the cached start and `P′` on average. Its output is
  what today's planning typed, since the plan's text is the irreducible part. The project's explorer
  is kept as recorded.
- **Sign-off** takes 4 requests, plus 3 per fix task, an estimate:
  - the four are the phase reviewer's dispatch, the triage decision, the sign-off step and the final
    report;
  - a fix task's three are `next`, the executor and `next`, and the recorded fix tasks closed
    `not-asked`;
  - each request reads `P′` + 4000 and writes 600, and emits 250, plus 1000 for the final report,
    all estimates;
  - the agents are the project's reviewer as recorded, + `0.005` for its filing request (an
    estimate), and the fix executor as recorded.

  The model prices one phase review at what the recorded one cost. In these sessions the plugin's
  review step and the project's own rule 5 merged into one review. Whether they still do under the
  driver is unmeasured, and T11's probe reads it.

Written out for `whole-C-3`:

- cycle main loop: 0.2e-6 × (14 × 41358 + 3000 × 13 / 2) + 8.0e-6 × 3000 + 20e-6 × 3500
  = 0.1197 + 0.0240 + 0.0700 = `0.2137`;
- cycle agents: 0.5219 + 0.1953 − 0.0134 + 0.0654 − 0.0429 = `0.7263`;
- cycle: `0.9400`, which is 1.72 times A's mean;
- planning: 0.2e-6 × 5 × (10950 + 41358) / 2 + 8.0e-6 × (41358 − 10950) + 20e-6 × 6467
  = 0.0262 + 0.2433 + 0.1293 = `0.3988`;
- sign-off, with its fix task: 0.2e-6 × 7 × 45358 + 8.0e-6 × 4200 + 20e-6 × (1750 + 1000) + 0.1715
  + 0.005 + 0.0666 = `0.3952`;
- whole: 0.3988 + 0.9400 + 0.3952 = `1.7340`, which is 3.17 times A's mean and 2.06 times B's.

The other two sessions are the same arithmetic on their own readings.

**G2, the per-task review on computed signals**, runs one review where the sessions ran three
(C14). A task with no review takes two requests: dispatch the executor, then `next`. So
`k` = 4 + 2 × 2 + 2 = 10, `W` = 1000 + 2 × 600 and `O` = 2500. The agents are the executors, a third
of the reviewers, C3's extra requests for three executors and one reviewer, less the trims on the
requests that remain.

**G1, the per-task review at the phase**, gives `k` = 2 × 3 + 2 = 8, `W` = 1800 and `O` = 2000.
The agents are the executors with their extra requests, less their trim. Sign-off gains `0.0261`
for the phase reviewer reading three returns (C14).

| Rung | Guarantee | Per-task ratio, `whole-C-3` / `-C-1` / `-C-2-r`; mean | Whole ÷ A's mean | Whole ÷ B's mean |
|---|---|---|---|---|
| 0, today, measured | as today | 4.16 / 3.95 / 4.74; 4.28 | 10.29 / 9.27 / 10.24; 9.93 | 6.67 / 6.01 / 6.64; 6.44 |
| 1 | **no change** | **1.72 / 1.64 / 1.83; 1.73** | 3.17 / 3.54 / 3.57; 3.43 | 2.06 / 2.29 / 2.32; 2.22 |
| 1 + G2 | the per-task intent check becomes conditional | 1.34 / 1.26 / 1.47; 1.36 | 2.80 / 3.16 / 3.21; 3.06 | 1.81 / 2.05 / 2.08; 1.98 |
| 1 + G1 | the per-task intent check moves to before the merge | **1.17 / 1.09 / 1.30; 1.19** | 2.67 / 3.03 / 3.09; 2.93 | 1.73 / 1.97 / 2.01; 1.90 |

Each ratio is derived: the predicted cycle or session divided by `0.547004` or `0.843470`. The
predicted cycles are:

- rung 1: `0.9400`, `0.8967`, `1.0001`;
- G2: `0.7356`, `0.6895`, `0.8020`;
- G1: `0.6419`, `0.5943`, `0.7114`.

The predicted sessions are:

- rung 1: `1.7340`, `1.9347`, `1.9550`;
- G2: `1.5296`, `1.7275`, `1.7569`;
- G1: `1.4619`, `1.6584`, `1.6924`.

Rung 0's mean is the measured cycles' mean, 2.3424 / 0.547004.

**Where each rung-1 saving comes from**, taken in the order the tasks would land, on the cycle's
modelled main loop:

| | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| modelled today | `1.5552` | `1.5027` | `1.8171` |
| the prose leaves the prefix (C2, C4, C8) | `−0.4859` | `−0.4452` | `−0.7345` |
| the driver with computed briefs and terse output (C9, C3, C10) | `−0.8555` | `−0.8314` | `−0.8790` |
| rung 1's cycle main loop | `0.2137` | `0.2262` | `0.2036` |
| agents: C3's requests less C13's trims | `+0.0225` | `+0.0248` | `+0.0187` |

The prose step is `main(k, P − prose − bodies + 4500, W, O)` at today's `k`, `W` and `O`. The
driver step then sets `k`, `W` and `O` to rung 1's and removes nine tenths of the script output.

**Rejected rungs, priced** (section 3):

| Option | Effect on the cycle | Guarantee given up |
|---|---|---|
| one executor per phase (C11) | `+0.0468`, a cost | per-task input isolation, the parallel wave |
| a cheaper main-loop model (C12) | about `+0.12`, a cost | none in the tables; decision quality unmeasured |
| the light path with a hook (C15) | about `+0.065`, a cost | input isolation |
| a forked reviewer with a hook (C15) | `+0.047` a task, a cost | input isolation, `phase.review.model` |
| `omitClaudeMd` (C13) | about `−0.02` | none in the tables; it drops the project's rules |
| a one-hour agent cache (C13) | `+0.2396`, a cost | none |

**The single-task shape**, for continuity with section 5.5's earlier set, on `feature-C-1`. Plain
there is `0.298019`, derived: (0.284359 + 0.311679) / 2 (the analysis, section 3). Today's session
is 5.87 times that, and the earlier set predicted 3.37 (1.0047 / 0.298019).

- **Rung 1 with the recorded Opus executor**: `0.6444`, which is 2.16 times plain. The main loop is
  `0.1625`: five requests at a prefix of 22695 tokens, 11891 cached + 9304 written + 1500 of thin
  body. The agents are `0.4819`, the executor `0.3998` and the reviewer `0.0957`, + `0.0226` of C3's
  requests − `0.0362` of trims.
- **Rung 1 with the executor's own tokens priced on the Sonnet row**: `0.4718`, which is 1.58 times
  plain. The executor would cost `0.2179`: 31513 × 2.5e-6 + 180263 × 0.2e-6 + 10306 × 10e-6.
- **Rung 1 + G1**: the reviewer, its two requests, its trim and one main-loop request leave, `0.1043`
  in all. That gives `0.5401`, 1.81 times plain, with the Opus executor, and `0.3675`, 1.23 times
  plain, with Sonnet.

An isolated executor on the same model as plain already cost 1.34 times plain on its own (0.3998 /
0.298019). It pays a start, a brief and a return on top of the work. So which model the plan gives
a task's executor moves the per-task ratio as much as any rung does. The arm C plans gave every task
Sonnet (the results document's section 2.3).

### 5.2 The recommended set

**Rung 1: the main loop keeps the decisions, and a script performs every step that needs none.** It
hands the model what it needs by path, prints each rule at the step it applies to, and asks every
judgement as a named decision. That is C9, with C2, C3, C4, C8 and C10 as its parts, the agent half
of C13, the planning batch and sign-off as one step. Section 6 has its tasks T1 to T4 and T7 to T10.

**It meets the per-task ceiling in every recorded whole-feature session, and not the ideal**: 1.64 to
1.83 times plain, a mean of 1.73. Those plans gave every executor Sonnet. **In the single-task shape
with an executor on the plain session's own model it does not:** 2.16 times plain on `feature-C-1`,
and only G1 brings that under the ceiling, to 1.81 (section 5.1).

It is the structurally correct set for three reasons, and cost is not one of them:

- **It moves rules toward mechanisms.** The task prose admits nothing checks a return's shape, its
  stamp, or a retry's context. The first two become a verb's exit code, and the third is computed
  by the brief script. The order of a task's steps becomes a script's order rather than a
  paragraph's. No enforced row is touched.
- **It takes the existing direction of travel.** Every verb that replaced a prose procedure has moved
  work off the model. The earlier audit said this direction "should continue", in its section 4.6.
- **It makes the model's judgement visible.** Today a judgement point is a sentence the model may or
  may not reach in some 76000 tokens of reference prose (section 1.5.3). Under the driver it is a
  printed decision with its options, which the transcript records.

How each guarantee is held under it:

| Guarantee | Held today by | Held under rung 1 by |
|---|---|---|
| enforced rows (hooks, `verify-invariants.py`, the agents' `tools:` lines) | themselves | themselves, untouched |
| the recorded gate, independent of the executor's claim | the main loop calling `run-test-gate.py --record` | the driver calling it; the model no longer transcribes the result |
| the stamp comparison | the main loop calling `stamp-verification.py compare` | the driver calling it, printing which field moved |
| a return's shape and stamp | nothing (`execute-task.md:168`, `:249`) | the filing verb's exit code (C3) |
| the per-task intent check | the reviewer's dispatch, followed | the driver printing the dispatch; the close refusing without the reviewer's filed return or `--intent not-asked` with a basis (C3) |
| each followed rule | a sentence in prose read up front | the same sentence printed at its step or stated in the agent prompt; T2's anchor lint fails a followed row that resolves to neither |
| the reviewer cannot edit | its `tools:` line | the same line; the filing verb's one write is held as C3 says |

**Facts about the recommended set, not reasons for it.**

- **Effort.** It adds a driver entry point (T4), extends `audit-lookup.py brief` and `audit-task.py`
  (T3), adds a batch `add` (T9) and a terse success line to each verb the driver calls (T7). It
  shrinks five command bodies and both agent prompts (T2, T8) and adds one lint and one ceiling gate.
- **Blast radius.** Every command that names a reference file, the tests and drift lints that name
  them (section 3, C2, has the commands that count them), both agent prompts, the README's followed
  table, `PLUGIN-BUILD-GUIDE.md`, and `tools/stream-cost.py`'s cycle rule.
- **Risk.** A followed rule may stop reaching the model at the moment it applies, and a driver
  defect would misdrive every run. The anchor lint (T2) and the driver's selftests (T4) hold
  against them. T11's probe reads both before the full benchmark.

**The ideal, and the ceiling for a task whose executor shares plain's model, need one guarantee
change, and that is the user's decision** (section 8, decision 1):

- **G1, the per-task intent check at the phase**: 1.09 to 1.30, a mean of 1.19. This meets the ideal
  on the arm's mean, in `whole-C-3` and in `whole-C-1`. It misses in `whole-C-2-r`, at 1.30, whose
  executors cost the most.
- **G2, gated on computed signals**: 1.26 to 1.47, a mean of 1.36. It does not meet the ideal.

**Recommendation for the decision: G1.** It puts the check where its result was consumed. In
both sessions where a per-task review found something, the task was committed in the same request,
and the finding was acted on at the phase (section 1.6). G1 also makes coverage a script's refusal
rather than a dispatch the main loop remembers. G2's trigger fired on the command-line task in every
session, because the red-first helper cannot classify an `argparse` exit (the results document's
section 4.4). It measures the helper's limit, not the task's risk.

**G1's guarantee change, and how it is held instead.** Today a task's claim is checked against its
description before that task commits. Under G1 it is checked before the phase merges.

- **Held by:** the phase reviewer's computed brief carries every task's filed return and description
  verbatim, and asks for one binding per task. The sign-off verb refuses, writing nothing, while any
  task of the phase lacks an intent answer from that review or a `not-asked` with its basis. The
  refusal is the mechanism, and T6 pins it with a case.
- **The consequence to publish:** a misread task is found after its commit, not before. Its repair is
  a fix task inside the phase, as both recorded per-task findings already were, rather than a
  re-spawn before the commit. A key with a default of `always` keeps today's behaviour. A default of
  `phase` would be a major release (section 2).

### 5.3 How far the margin can be trusted

Rung 1's worst session is `whole-C-2-r` at 1.83 times plain. The ceiling is 2.0, so the margin is
2 × 0.547004 − 1.0001 = `0.0939` of cycle cost. The estimates it rests on, each with what doubling
it would cost in that session:

| Estimate | Value | Doubled, added to the cycle | Ratio then |
|---|---|---|---|
| output per request | 250 tokens | 14 × 250 × 20e-6 = `0.0700` | 1.96 |
| requests per task | 4 (C7's 5 instead) | 3 × (37755 × 0.2e-6 + 250 × 20e-6) = `0.0377` | 1.90 |
| writes per task | 1000 tokens | 3000 × (8.0e-6 + 0.2e-6 × 13 / 2) = `0.0279` | 1.88 |
| thin bodies | 4500 tokens | 4500 × 0.2e-6 × 14 = `0.0126` | 1.85 |
| the wave's waits | 2 | 2 × (37755 × 0.2e-6 + 250 × 20e-6) = `0.0251` | 1.87 |

Any one of them can double and the worst session stays under the ceiling. Doubling the first two
together would take it to 2.05. So T11's probe reads each of them on its own before the full
benchmark runs (section 7).

The other side of the margin is the executors. They are measured, not estimated, and they are what
`whole-C-2-r` spent most on: 32 executor requests, against 26 and 23 (section 1.5.5's request
counts). Two of its executors were resumed after permission refusals of heredoc writes (the results
document's section 5.5). That friction belongs to the benchmark's approval-less permission mode,
and a user who approves the write does not pay it.

### 5.4 The phase overhead: budget and value tests

**Budget, per phase, for a feature of this size**, predicted under rung 1 and set as a ceiling the
after-study checks. The project's own agents (the explorer, and the reviewer when it is the
project's) are shown apart, because arm B pays them too.

| Part | Today, measured | Rung 1, predicted | Budget |
|---|---|---|---|
| planning, without the project's explorer | `1.3231` to `1.4924`, plus `0.2493` and `0.3219` of explorer | `0.3832` to `0.4108` | `0.45` |
| the run's preflight | `0.0532` to `0.2067` | inside the cycle's first `next` | `0` apart |
| sign-off without a fix task, with its review | `0.6367` to `0.9637`, review `0.2364` to `0.2472` | `0.2498` to `0.2720` | `0.30` |
| the run's close | `0.2005` to `0.2457` | inside sign-off's last step and the report | `0` apart |
| **phase overhead** | **`2.9071` to `3.3509`**, with fix tasks and explorers | **`0.63` to `0.68`** | **`0.75`**, 1.37 times A's mean |
| each fix task | `0.3990`, `0.5580` | `0.1232` in `whole-C-3` | under the per-task target, as a task |

Planning without the explorer is derived: 0.3988, 0.6601 − 0.2493 and 0.7051 − 0.3219. Sign-off
without a fix task is the sign-off formula at 4 requests:

- `whole-C-3`: 0.2e-6 × 4 × 45358 + 8.0e-6 × 2400 + 20e-6 × 2000 + 0.1715 + 0.005 = `0.2720`;
- `whole-C-1`, on its own readings: `0.2693`;
- `whole-C-2-r`: `0.2498`.

The phase overhead is the sum of the two, for example 0.3988 + 0.2720. The fix task is three
requests at 45358 tokens plus its recorded executor:
3 × (0.2e-6 × 45358 + 8.0e-6 × 600 + 20e-6 × 250) + 0.0666 = `0.1232`.

**Value tests.** Each phase-level step names what it must catch to stay, and where that is read. A
step that costs no model request stays at no cost. Its value test applies the day it needs one.

| Step | What it must catch to stay | Read from | What these sessions show | Verdict now |
|---|---|---|---|---|
| planning | its floor, the tasks the cycle runs, needs no test. Beyond the floor it must name the choices the request leaves open, as decisions | the plan's decisions, and the hidden tests of the after-study | no choice named. The refund remainder, which the hidden test checks, was fixed silently in every plan | keeps its floor. T9 adds the open-choice list to the plan file, and the after-study decides whether the list stays |
| phase review | a finding at medium or above, or a plan that departs from the request | the plan's findings and the hidden tests | seven low findings, one fixed, nothing graded moved | stays, as the one review arm B pays too. Its brief gains the request verbatim and the question of where the plan chose what the request left open (T3). If the after-study shows nothing above low and no departure caught, running it only on a computed signal becomes the user's decision |
| phase gate | red where every task gate was green | `docs/audit/evidence` rows | green in every session | stays, as a script step inside sign-off with no model request (T10) |
| invariants check | a breach | `verify-invariants.py` | none | stays, the same way |
| findings bookkeeping | nothing to catch: it is a cost | requests per finding | one request per finding, `0.1253` to `0.4305` | one batch call (T10) |
| fix tasks | a change a graded measure or a later review reads | the fix task's diff and the after-study's grade | tests added for low findings, nothing graded moved | each fix task becomes a named decision in triage, printed with its predicted price |
| per-task intent review, if kept per task | a finding that changes the task's commit before it lands | the stream: a `finding` call followed by a re-spawn, not a commit | none: both tasks with findings were committed in the request that recorded them | moves to the phase under G1 |

**The value lever the evidence names.** No step today compares the plan with the request, so no
step can catch the class of failure every arm shared. The phase review's computed brief gains the
request text, saved verbatim by `/audit:phase add`, and one fixed question: where does a task
choose something the request leaves open? That costs about 1000 tokens of brief. The after-study's
hidden test `RefundAmounts.test_partial_returns_add_up_exactly` is its measurement. Whether a review
so briefed would have named the remainder order is unmeasured.

### 5.5 The set recommended before the target, kept as dated history

This was section 5 until 2026-10-07. It recommended C3 and C7, with C2 and C8, and C4 as the rule for
what a cut may delete. For one task it predicted `1.0047` against the measured `1.7484`. That is
3.37 times plain, so it misses the per-task target, and rung 1 replaces it. Its arithmetic is still
the single-task model's, and sections 1 to 4 cite it, so it stays below unchanged.

**Prediction for the recommended set.** Computed once, with the section 1.2 model. The prose target is
50000 bytes read first for `/audit:run`: C2's keep class less the brief prose C3 replaces (13353), the
gate and review prose C7 folds (14259), and the preflight a script can run (7717), plus about 6
kilobytes of residual sentences. That figure is an estimate.

The state after the change is one pipeline, whatever the per-task shape is today. It is computed
from `feature-C-1`'s rows and set against both of section 1.2's baselines:

- **Requests per task** go to 5, from 8 at k = 8 and from 6 at k = 6. So m = 4 + 5N.
- **The run class.** The prose falls by 38405.6 tokens, derived: 57417 − 50000 / 2.63. The run
  write becomes 0.54056 − 38405.6 × 8.0e-6 = `0.23332`, and a further request reads 41055 run tokens
  instead of 79461. Its output (`0.0109`) and the early reads (`0.0110`) are unchanged. So
  R(m) = 0.23332 + 0.0109 + 0.0110 + 41055 × r × m.
- **The task work a run pays once,** `L(m)`, is unchanged. The run still reads the manifest, takes
  and releases the lock, and reports.
- **The content a task leaves in the main loop** falls from 21857 (17059 at k = 6) to 5949. That is
  2616 + 140 + 1458 + 140 + 1595, by request:
  - the start, 2616;
  - the dispatch, 140: a 60-token hand-off and an 80-token hand-back;
  - the gate, 1458;
  - the reviewer dispatch, 140;
  - the commit, 1195, plus 400 for the folded close.
- **The task work per task** falls from 0.7049 to `0.3872` at k = 8, by `0.3177` (derived):
  - output no longer typed, (2840 − 60) + (2817 − 60) + (1723 + 1769 − 100) + 630 = 9559 tokens,
    × o = `0.1912`;
  - content no longer written, 21857 − 5949 = 15908 tokens, × w = `0.1273`;
  - that content's reads within the run. Today they are
    (2616 × 8 + 5159 × 7 + 1458 × 6 + 1229 × 5 + 3646 × 4 + 1195 × 3 + 2985 × 2 + 3569 × 1) × r
    = `0.0199`. After, they are (2616 × 5 + 140 × 4 + 1458 × 3 + 140 × 2 + 1595 × 1) × r = `0.0040`.
    That saves `0.0159`;
  - the three removed requests' input, `0.00002`;
  - less C3's two extra requests per agent, `0.0054` and `0.0113`.

  Against k = 6, the same after state is 0.6113 − 0.3872 = `0.2241` lower per task.
- **The square term** at N = 5 becomes 5949 × 0.2e-6 × 5 × 10 = `0.0595`.

| | run | task, once per run | task, per task | file | after | today, k = 8 | saving | today, k = 6 | saving |
|---|---|---|---|---|---|---|---|---|---|
| N = 1 | `0.3291` | `0.0755` | `0.3872` | `0.2129` | `1.0047` | `1.7484` | `0.7437`, 42.5% | `1.6217` | `0.6170`, 38.0% |
| N = 5 | `0.4933` | `0.0883` | `1.9955` | `1.0645` | `3.6416` | `6.2983` | `2.6566`, 42.2% | `5.5200` | `1.8784`, 34.0% |

The two one-off requests account for the difference between the two savings: `0.1266` at N = 1 and
`0.7782` at N = 5 (derived before rounding: 0.743651 − 0.617005 and 2.656598 − 1.878364). If neither
recurs, that part is not there to save. The revision at `9501aa91` gave `0.1256` and `0.7725`, on
the k = 6 baseline section 1.2 now corrects.

Section 0 gives the first draft's figures for this set and what changed since. The early reads,
`0.0110`, were in its run line without being named. The model is anchored on `feature-C-1`'s prose,
151022 bytes, which is 2679 fewer than `7b489337`'s. That understates today's cost, so the saving is
conservative. The amount is `0.0106` at N = 1 and k = 8, and `0.0102` at k = 6, derived:
2679 / 2.63 × 10.4e-6 and × 10.0e-6.

**The phase run form, prose only, with `S` = 6 assumed.** Today `/audit:phase` reads 242068 bytes up
front, and every request after that carries them. After the change it reads 64470 bytes during the
tasks: the run section of `phase.md`, 14470 by the section 10 command, plus the 50000 above. It reads
`phase-signoff.md`'s 48598 bytes only at sign-off. With m = 4 + kN + S later requests:

- **today**, 242068 / 2.63 = 92041 tokens × (8.0 + 0.2 × m) / 10^6:
  - at N = 1, `1.0677` (m = 18, k = 8) and `1.0309` (m = 16, k = 6);
  - at N = 5, `1.6567` (m = 50) and `1.4727` (m = 40);
- **after**, 64470 / 2.63 = 24513 tokens over m = 4 + 5N + 6, plus 48598 / 2.63 = 18478 tokens read at
  sign-off and carried by its 6 requests:
  - at N = 1, [24513 × (8.0 + 0.2 × 15) + 18478 × (8.0 + 0.2 × 6)] / 10^6 = 0.2696 + 0.1700 =
    `0.4396`;
  - at N = 5, 24513 × (8.0 + 0.2 × 35) / 10^6 + 0.1700 = `0.5377`.

The planning verbs come on top of that, per invocation (C8).

Its facts (effort, blast radius, risk) and what it did not do are carried into section 5.2 for the
set that replaces it. One of them carries over unchanged: the reviewer gains one write, through a
write-once filing verb that derives its one path and never replaces a return already filed. The task
id and role it files under are the caller's word, so a filing under a role or a task not yet filed
stays a followed rule (C3, *Guarantees*).

## 6. Implementation tasks

These are the tasks of a new implementation phase. Together they reach rung 1 (section 5.1), and T6
adds G1 or G2 if the user decides it. **The user's order is fixed:**

1. implement;
2. run each task's micro-test;
3. run the full benchmark only after every task has passed its micro-test (section 7).

A micro-test confirms one fix without a full benchmark. It is an offline measurement, a
`stream-cost.py` reading of a recorded or synthetic stream, or at most one single-task paid probe
named with its expected cost. Only T11 holds a paid step. Every target is re-derived by
`tools/measure-context.py` or `tools/stream-cost.py` at the landing commit, with
`--bytes-per-token 2.63` where it applies. Until T1 lands, section 10's commands stand in.

| Task | Mechanism | Rung | Micro-test | Its cost |
|---|---|---|---|---|
| T1 | the instruments: spans, injected bodies, the rebuild fault | — | the arm C records re-read; twin fixtures | offline |
| T2 | no reference prose in the main loop; thin command bodies; anchor lint; ceiling gate | 1 | `measure-context.py --gate`; the anchor lint shown red | offline |
| T3 | computed briefs, filed returns, the phase reviewer's brief with the request | 1 | the filing verb's cases; brief sizes | offline |
| T4 | the step driver, four requests a task | 1 | a drive over a fixture plan | offline |
| T5 | calibration from the whole-feature sessions | — | done in this revision (sections 1.4 to 1.6) | — |
| T6 | G1 or G2, only if the user decides | G1/G2 | a drive with the key set; sign-off's refusal | offline |
| T7 | terse success output | 1 | each verb's success line, sized | offline |
| T8 | trimmed agent prompts; the agents' own `submit` | 1 | `measure-context.py` agent totals | offline |
| T9 | planning in one batch, with the request's open choices | 1 | the batch verb's cases; the `add` body's size | offline |
| T10 | sign-off as one step; findings in one call | 1 | a drive through sign-off | offline |
| T11 | the probe, then the full benchmark | — | one single-task paid probe, then three sessions | about `0.64`, then about `5.6` |
| T12 | optional: the TTL trade in the doctor | — | twin synthetic sessions | offline |

### T1 — The instruments read what this design predicts

- **Files:** `tools/measure-context.py`, `tools/stream-cost.py`.
- **What:**
  - `measure-context.py` gains `--sections`: bytes per heading, and per declared line range for a
    file with one heading, under the classification table this document uses. It also gains entries
    for `/audit:phase add`, `/audit:task add`, and the phase run form before and at sign-off.
  - `stream-cost.py` gains, per context, the longest gap between consecutive requests and every
    dispatch's `start_cR` by agent type. It also counts plugin command-body injections and reference
    reads per session, and sums the reference reads by the span their request falls in: planning,
    before the cycle, the cycle, after it (C2's *Confirming reading*).
  - `stream-cost.py` prints the task cycle (section 1.1) as a section of its own. It names the
    cycle's first and last request and the task ids its `done` calls name. Per task held, it prints
    the cycle's main-loop requests, its main-loop output, the task-class tokens its requests put into
    the main loop, its largest outputs, and its priced cost by class with the agents its requests
    dispatched. The requests before and after the cycle are printed apart, with any `done` call
    after it, so a cycle closed before a task planned inside it shows what it left out. A session
    with no `start` call prints that it has no task cycle, and one with no `done` after its start
    prints that its cycle never closed. Neither reads as zero.
  - The bounds are read off the verb and its operand, never off the text around them. `done --help`
    names no task, so it closes nothing (`feature-C-1`, request 11). T4's composite verbs run
    `start` and `done` inside them, so T4 adds them to this rule in the same change. Without that,
    an after-study session would have no cycle to read.
  - `stream-cost.py` prints planning as a row of its own. Planning opens at the first request
    before the cycle that plans, in either of section 1.1's two shapes. It closes at the last
    request before the cycle that calls the `add` or `add-phase` verb, or at the request that opened
    it when none does. A run's preflight, manifest read and lock come after its last planning verb,
    so they fall in neither span. No per-task reading uses this row. Section 7's whole-set reading
    does, through its `$task` in `per stage, by what it put there`, and so does C8's count.
  - The planning rule keys on the `Skill` call because that is how arm C invokes a command:
    `whole-C-2` and `whole-C-3` both open with `{"skill": "audit:phase", "args": "add"}`. The call
    was denied in `whole-C-2` (`<x2>/invalid.jsonl`) and allowed in `whole-C-3`.
  - `stream-cost.py` reads every `result` event. **This part has landed**, at the result-reading
    commit (section 0). `9501aa91` keeps the last one (`tools/stream-cost.py:234-235` there), and
    `whole-C-3` holds three. Read from the last block alone, its main loop `DISAGREE`s with the
    stream and opus prices `DIFFER by -0.507663` (the `reconstruction:` and `pricing:` lines at
    `9501aa91`). What the CLI writes in each result was read off the arm C sessions before the rule
    was set, with section 10's result command:
    - `usage` is its own stretch's main loop. A stretch opens at an `init` event, and the main-loop
      requests up to the next one sum to that stretch's `usage` in every stretch of `whole-C-1`,
      `whole-C-3` and `whole-C-2-r`. Summed over its results, `usage` is `whole-C-3`'s main loop:
      in 122, cacheW 211809, cacheR 10626961.
    - `modelUsage` and `total_cost_usd` are the session's. Each session repeats them unchanged in
      every result, and `total_cost_usd` is the sum of one `modelUsage`'s `costUSD`. Summed over
      the results, they would count every subagent once per result.
    - Every result sits at the end of its stream, so a stretch is told by its `init` event, not
      by where its result sits.

    At the result-reading commit, condensed from each report's header, `reconstruction:` and
    `pricing:` lines (`python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`):

    ```
    <x2>/whole-C-3    3 result events; the main loop agrees in every stretch
                      claude-opus-5-5   priced=4.856048 costUSD=4.856048  agree
                      claude-sonnet-5-5 priced=0.770360 costUSD=0.770359  agree
    <x2>/whole-C-1    3 result events; the main loop agrees in every stretch
                      claude-opus-5-5   priced=4.373351 costUSD=4.373351  agree
                      claude-sonnet-5-5 priced=0.695109 costUSD=0.695109  agree
    <x2>/whole-C-2-r  5 result events; the main loop agrees in every stretch
                      claude-opus-5-5   priced=4.823008 costUSD=4.823008  agree
                      claude-sonnet-5-5 priced=0.777877 costUSD=0.777877  agree
    ```

    `whole-C-3`'s sonnet row prints two values a digit apart under `agree`: with `--json` they
    differ by 2.2e-16, and six decimals round them apart. Each model's total is whole. Its split
    across stages is not yet: each report also prints an `unattributed` row holding a negative
    `claude-sonnet-5-5` cache read, the `belong to no request` line of `reconstruction:` (−67063,
    −57341 and −70856, in the block's order). In `whole-C-3` that is the two final requests
    rebuilt for `opKrv7` and `KRKraC`, cacheR 33679 and 33384 in their `dispatch` lines. Section
    10's dispatch command shows why. Both were started in the background: the call's tool result is
    a notice that an async agent launched, and each agent's last request in the stream is its own
    report, as text. So their final requests were not missing, and the rebuild counts each twice.
    In `whole-C-1` the two dispatches launched that way sum to its row exactly. In `whole-C-2-r`
    no set of its dispatches whose last request is text alone does, so its row is not yet
    explained. The fault is the final-request rebuild's, not the result reading's, and it moves
    cost between one model's stages, never out of the session.
  - What follows the cycle holds sign-off, any fix task it runs and the run's close. T1 prints them
    as three parts, bounded as section 1.5.2 bounds them. A fix task runs from an `add` after the
    cycle to that task's `done`. The close starts at the lock release, or after the landing.
  - **Added by the cost target.** `stream-cost.py` sizes each user text block of the main loop, so
    a command body a `Skill` call injects is a source of its own, `command body: <skill>`. Today
    the write is split among the request's other sources at 0.01 bytes per token (section 1.5.7).
  - **Added by the cost target.** A dispatch whose tool result is the async-launch notice keeps its
    last visible request as its final and rebuilds none. That removes the rebuild fault's phantom
    final (section 1.5.7), and the `unattributed` row it leaves.
  - **Added by the cost target.** The span command's other readings become the tool's own: the
    prefix the cycle's first request read, by origin; what the cycle read, by origin; and each
    dispatch's start, read and written.
- **Target:**
  - `measure-context.py --ref 7b489337c06d --sections` prints this document's class sums for the three
    `/audit:run` files (keep 77811, conditional 27767, elsewhere 25037, maintainer 23089).
  - `stream-cost.py <x>/feature-C-1/stream.jsonl` prints `start_cR` 0 for both agents and a longest
    main-loop gap.
  - On `feature-C-1`, the same command prints a cycle of requests 6 to 13 holding P1.1, with
    8 requests, 21857 task-class tokens, a task class of `0.7049`, a file class of `0.2129` and an
    estimated 11374 output tokens (section 1.1). Its `planning` row is empty, and every other figure
    this document quotes from that session stays unchanged.
  - On `whole-C-2`, a `planning` row of one request, the denied `Skill` call, and no task cycle. The
    rule this replaces closed planning only at another command or at a start. That session made
    neither, so the old rule read every one of its requests as planning.
  - On `whole-C-3`, planning is requests 1 to 12. Requests 13 and 14 fall in neither span. The cycle
    is 15 to 36, holding P1.1, P1.2 and P1.3, and P1.4-fcb's `done` is printed after it. Its main
    loop agrees with its `result` events, which the result-reading commit already prints.
  - Twin fixtures, each pair built so that only the rule tells them apart:
    - a run whose preflight and lock sit between the last `add` and the first `start`, against one
      whose `start` follows the last `add`. The `planning` row holds the same requests in both, and
      a rule that closed planning at `start` fails the first.
    - a phase whose sign-off adds and runs a fix task after the last task's `done`, against one whose
      sign-off adds none. The cycle holds the same requests and tasks in both, and a rule that closed
      it at the last `done` fails the first.
  - **Added by the cost target**, on the three arm C records:
    - the spans and their billed figures print as section 1.5.2's table;
    - `whole-C-3`'s two `/audit:phase` injections print as `command body` rows of about 15900 and
      16200 tokens, from 42897 and 42894 bytes;
    - the `unattributed` row is gone, and each model's total is unchanged (`4.856048` and
      `0.770360` for `whole-C-3`);
    - a twin pair of synthetic streams, one launching an agent in the background and one in the
      foreground, prices the agent the same in both.
  - Each new selftest case is shown red before it is trusted.
- **Micro-test:** the targets above. They are offline and cost nothing.

### T2 — The prose leaves the main loop (C2, C4, C8, strengthened by C9)

- **Files:**
  - `plugins/audit/reference/*.md`. Each rule is re-homed in one of three places: the text the driver
    prints at the step the rule applies to (T4); the agent prompt that acts on it (T8); or, for prose
    that explains what a script enforces, `PLUGIN-BUILD-GUIDE.md` and the script's docstring (C4's
    rule);
  - the bodies of `plugins/audit/commands/{phase,run,next,resume,review,task}.md`, cut to the driver's
    loop and the verb's own section;
  - `plugins/audit/scripts/_refs.py`, and the tests that name reference files;
  - `plugins/audit/README.md`, the followed table's "Stated in";
  - `PLUGIN-BUILD-GUIDE.md`, `CHANGELOG.md`;
  - `tools/measure-context.py`, `tools/verify.sh`, `.github/workflows/ci.yml` and
    `tools/gate-parity.py`, for the ceiling gate below.
- **Mechanism.** No pipeline command tells the main loop to read a reference file. What a step needs,
  the driver prints at that step. A new lint checks that every followed row's "Stated in" resolves
  to a step text the driver prints or to an agent prompt's section. It is shown red before it is
  trusted. A ceiling gate, `measure-context.py --gate`, holds the maxima below in CI. It reads the
  same `total` line per entry and nothing else, so the gate and this table cannot measure two
  different things.
- **Target** (`python3 tools/measure-context.py --ref <commit> --bytes-per-token 2.63`, each entry's
  `total` line: its command body without the frontmatter, plus the files it reads first):

  | Entry | Total, at most | At `f7eaade4` |
  |---|---|---|
  | `/audit:phase` run form | 4000 bytes, no file read first | 242068 |
  | `/audit:phase add` | 8000 | 242068 |
  | `/audit:task add` | 8000 | 108170 (section 10's command, at `7b489337`) |
  | `/audit:run`, `/audit:next`, `/audit:resume` | 4000 each | 159474 for `/audit:run` |
  | sign-off (`/audit:review`) | 6000 | 149138 |

  These ceilings are where rung 1's 4500 tokens of bodies come from (section 5.1). The targets this
  task carried before the cost target, kept once as dated history, were 86000 for `/audit:run`,
  30000 for `/audit:phase add`, 45000 for `/audit:task add` and 95000 for the run form.
- **Micro-test:** the ceiling gate and the anchor lint, each shown red before it is trusted. They are
  offline and cost nothing. On T11's probe, the prefix the cycle's first request reads is at most
  25000 tokens (section 1.5.3's first table, read by T1).

### T3 — Computed briefs and filed returns (C3)

- **Files:**
  - `plugins/audit/scripts/status/audit-lookup.py`, whose `brief` writes the whole brief;
  - `plugins/audit/scripts/manifest/audit-task.py`, for the filing verb and `done --from-return`;
  - `plugins/audit/agents/audit-executor.md`, `plugins/audit/agents/audit-reviewer.md`;
  - the task prose, `plugins/audit/scripts/_refs.py` and `PLUGIN-BUILD-GUIDE.md`;
  - the tests of both scripts.
- **The reviewer's write.** `audit-reviewer.md` gains one *May* line: one call of the filing verb.
  Its *Must not* keeps "anything that writes", with that call as the only exception. The filing
  verb takes the task id and the role and no path, and derives the one file it writes from them and
  the task's current start. Its tests pin these:
  - a path-like argument is refused;
  - a malformed return writes nothing;
  - the written path equals the derived one;
  - a second filing for one task and role in one start is refused, and the first return is
    byte-identical afterwards. The same case files the other role, and files again after a
    re-start, and both of those must write. Without that half, a verb that refused every second
    filing for a task would pass.
  - `brief` for the reviewer exits non-zero and writes no brief while the executor's return for the
    task's current start is unfiled. Once that return is filed, the brief is written and carries it
    byte-identical. Without that half, a `brief` that refused every reviewer brief would pass.
  - `done --from-return` refuses and writes nothing when the executor's return for the current
    start is missing. It also refuses when the reviewer's is missing and the close does not pass
    `--intent not-asked` with its basis, and when the only return filed is from an earlier start.
    It closes when both are filed for the current start, and when the executor's is filed and the
    close passes `--intent not-asked` with its basis. Without those halves, a close that refused
    everything would pass.

  Those cases hold the write to one derived path that never replaces a return already filed. They
  do not hold the task id and role to the caller's own. Those are the caller's word, so a filing
  under a role or a task not yet filed stays a followed rule. So does the reviewer running nothing
  else that writes, unenforced, as it is today (C3, *Guarantees*).
- **Added by the cost target: the phase reviewer's brief.** `/audit:phase add` saves the request's
  text verbatim beside the phase. The sign-off reviewer's computed brief carries it, every task's
  description and filed return, and one fixed question: where does a task choose something the
  request leaves open? (section 5.4). Its case: a brief computed for a phase with a saved request
  holds that text byte-identical, and one with none says so rather than leaving the field empty.
- **Target** (`python3 tools/stream-cost.py <session>/stream.jsonl`, with T1's task cycle). Each
  reading is taken inside the cycle and divided by the tasks it holds, as C3's *Confirming reading*
  says:
  - no `brief for audit:audit-*` row above 200 tokens among the cycle's largest outputs;
  - the cycle's main-loop output at most 1500 tokens per task. Rung 1 predicts 1167, an estimate:
    14 requests × 250 / 3 tasks. The target before the cost target was 2350, with `feature-C-1` at
    11374 and the whole-feature sessions at 6461 to 7550 (section 1.5.4: 19382 / 3, 22650 / 3);
  - the tokens the cycle's requests put into the main loop, at most 1500 per task. Rung 1 predicts
    1000. The target was 7400 before.
- **Micro-test:** the filing verb's and the brief's cases, offline. On T11's probe, the readings
  above.

### T4 — The step driver: four main-loop requests a task (C9, superseding C7)

- **Files:**
  - `plugins/audit/scripts/governance/drive-phase.py`, a new entry point. It owes the five things
    `CLAUDE.md` names for a new `.py`: a `--selftest` with the `N/M cases passed` contract,
    `safe_stdio()` first in `__main__`, a row in `_deps.LAYERS`, a tree line and a section in
    `PLUGIN-BUILD-GUIDE.md`, and `_output.PATH_PREAMBLE`;
  - its suite, `plugins/audit/tests/test_drive_phase.py`;
  - `plugins/audit/scripts/manifest/audit-task.py`, `run-test-gate.py`, `stamp-verification.py`,
    `commit-task-work.py`, `audit-lock.py`, `close-phase.py` and `verify-invariants.py`, called and
    not re-implemented;
  - the bodies of `commands/phase.md`, `run.md`, `next.md` and `resume.md`, cut to the loop;
  - `tools/stream-cost.py`, whose cycle rule must read the driver's own `start` and `done`, in the
    same change (T1).
- **Mechanism.** `next <phase>` reads the plan and the filed returns, performs every due step that
  needs no judgement, and prints one instruction: `dispatch`, `decide`, or `done` (C9). A refusal
  prints the refusal and its remedy and stops. The recorded gate stays before the reviewer's
  dispatch.
- **Target**, read from T1's task cycle: its main-loop requests divided by the tasks it holds, at
  most 4, plus at most 2 for each wave. `feature-C-1` read 8 for its one task, and the whole-feature
  sessions 7.3 to 9.3 (section 1.5.4). The target this task carried before the cost target was 5,
  as C7's composite verbs.
- **Micro-test, offline:** a drive over a fixture plan of three tasks, one wave, with filed returns
  written by the test. Its cases:
  - the printed sequence is four model-facing steps per task;
  - every success print is at most 300 bytes;
  - a stale stamp prints the field that moved;
  - a refused verb stops the drive and prints the verb's own refusal.

  Each case is shown red against a mutated driver before it is trusted. On T11's probe: the cycle's
  main-loop requests, at most 4 for its one task.

### T5 — Calibrate the model from the baseline sessions (done in this revision)

- **What it asked:** read the task cycle's requests per task and `S`, the planning invocations and
  injections, the main loop's longest gap, and each later dispatch's `start_cR` off the whole-feature
  arm C sessions. Then replace each assumption of section 1.4 with its reading.
- **Done:** section 1.4's last table puts a reading beside every assumption, and sections 1.5 and 1.6
  hold the readings. They come from section 10's commands until T1 prints the same figures.

### T6 — Only if the user decides: the per-task review at the phase (G1) or gated (G2)

- **Files:** the config schema and `_config_rules.py` for `review.perTask` (`always` by default;
  `phase` for G1; `signals` for G2), the panel's control, the doctor's line, the driver's step (T4),
  the phase reviewer's brief (T3), and the sign-off verb in `audit-task.py`.
- **Mechanism.**
  - Under `phase`, the driver dispatches no per-task reviewer. The phase reviewer's brief carries
    every task's return and description, and asks for one binding per task. The sign-off verb
    refuses, writing nothing, while any task of the phase lacks an intent answer from that review or
    a `not-asked` with its basis.
  - Under `signals`, the driver dispatches the per-task reviewer only when the task's `redFirst` did
    not come back `proved`, or when the gate row disagrees with the filed return.
- **Micro-test, offline:** a drive over the T4 fixture with each value:
  - `phase` dispatches no per-task reviewer;
  - sign-off refuses with one binding removed from the phase review's return, and passes with it
    restored;
  - `signals` dispatches exactly the reviewers its two conditions select;
  - `always` drives as T4 does.

  Each case is shown red first.
- **Target:** the per-task ratio of section 5.1's rung for the chosen value. Its confirming
  sessions are the after-study, run with the key set.

### T7 — Terse success output (C10)

- **Files:** each verb the driver or the main loop calls (`audit-task.py`, `run-test-gate.py`,
  `stamp-verification.py`, `commit-task-work.py`, `audit-lock.py`, `verify-invariants.py`,
  `close-phase.py`, `validate-manifest.py`, `audit-lookup.py`, `audit-status.py`'s entry view), and
  one shared helper in `_output.py` for the success line.
- **Mechanism.** Success prints one line naming what was done and the record it wrote. `--verbose`
  prints today's text. A refusal prints in full, unchanged.
- **Micro-test, offline:** each verb's success path, run on its own selftest fixture, prints one line
  of at most 200 bytes without `--verbose`. With `--verbose`, the same path prints today's text
  unchanged. Each case is shown red against a verb that still prints the long form.

### T8 — Agent starts: trimmed prompts and the agents' own `submit` (C13)

- **Files:** `plugins/audit/agents/audit-executor.md`, `plugins/audit/agents/audit-reviewer.md`, the
  driver (T4) for `submit`, and the lints that pin the prompts' sentences (`return_shape_drift`
  and its neighbours in `_refs.py`).
- **Mechanism.** The executor's last act is one call: `drive-phase.py submit --role executor <task>`.
  It takes the stamp, runs the red-first helper on a `tdd` task, and files the return through C3's
  write-once verb. The reviewer files through `submit --role reviewer`. The prose that explained
  those steps leaves each prompt. `omitClaudeMd`, preloaded skills and `experimental.cacheTtl` are
  not taken (C13).
- **Target** (`python3 tools/measure-context.py --ref <commit>`): executor at most 9000 bytes,
  reviewer at most 7000 bytes. At `f7eaade4` they were 18790 and 15689.
- **Micro-test:** the two totals, and `submit`'s cases (a missing stamp refused, a malformed return
  writing nothing, a second filing refused), offline. On T11's probe: the executor's `start written`
  at most 16000 tokens on its first dispatch (`whole-C-3`: 18730).

### T9 — Planning in one batch, with the request's open choices (C8)

- **Files:** `plugins/audit/scripts/manifest/audit-task.py`, `commands/phase.md`'s `add` section,
  the plan's schema, and the tests.
- **Mechanism.**
  - `audit-task.py add --from-file <plan.json>` adds a phase and its tasks in one call, revalidates
    once, and refuses a malformed file writing nothing. The main loop writes the file with `Write`,
    because a JSON document on a heredoc was refused in every arm C session (the results
    document's section 5.5).
  - The file carries the request's text verbatim, which T3's reviewer brief reads, and a list of
    the request's open choices. The list may be empty; it is the field section 5.4's value test
    reads.
  - The `add` body is verb-scoped, at most 8000 bytes (T2).
- **Micro-test, offline:** the batch verb's cases:
  - a valid file writes the phase and its tasks;
  - a malformed file writes nothing;
  - a file whose task names a missing dependency is refused by name.

  Each is shown red first. Then `measure-context.py`'s `/audit:phase add` total.

### T10 — Sign-off as one step

- **Files:** the driver (T4), `audit-task.py`'s `finding` for a findings file, the sign-off section of
  the prose that remains, and the tests.
- **Mechanism.**
  - At sign-off the driver prints the phase reviewer's dispatch.
  - Then it prints one `decide` for the triage, listing each finding with its options and a fix
    task's predicted price.
  - Then it runs the phase gate, the invariants check, the sign-off verb, the commit, the landing and
    the lock release as one step.
  - Findings are recorded in one call from a file, never one per request.
- **Micro-test, offline:** a drive through sign-off over the T4 fixture:
  - the model-facing steps are the review's dispatch, the triage decision and the final step;
  - a red phase gate stops the step before the sign-off verb;
  - a findings file of several findings records all of them in one call.

  Each is shown red first.

### T11 — The probe, then the full benchmark

Only after every micro-test of T1 to T4 and T7 to T10 has passed. The steps and their costs are in
section 7.

### T12 — Optional: the main loop's TTL trade, printed by the doctor (decision 5)

- **Files:** a doctor check beside the others in `plugins/audit/scripts/status/_doctor_*.py`, reading
  the usage ledger through `plugins/audit/scripts/usage/`, and its tests.
- **Mechanism.** From a recorded session of the user's own, the doctor prints three things: the
  longest gap between main-loop requests, the one-hour writes, and their price at each TTL. It
  recommends nothing the gaps do not support, and the setting stays the user's.
- **Micro-test, offline:** a twin pair of synthetic sessions, one with every gap under five minutes
  and one with a gap over it. Each prints its own longest gap and the trade it implies, and the pair
  differ only there. It is shown red first.
- **Open before it is written:** whether the usage ledger holds per-request times. If it does not,
  the task first decides where the doctor reads them from.

## 7. The confirming measurements, in the harness's terms

**The order is the user's and is fixed: implement, micro-test each fix, then the full benchmark.** No
paid session runs until every offline micro-test of section 6 has passed. Nothing enforces this order,
and the probe's stop rule below is not enforced either. The orchestrator's recorded runs, each micro-test's
verdict before the probe and the probe's readings before step 3, are the evidence that the order
held.

**Before.** The whole-feature study's arm C sessions are `whole-C-3`, `whole-C-1` and `whole-C-2-r`,
in `<h2>/order.json`'s seeded order. They ran at `pins.json` → `pluginSha` `f7eaade4`, whose plugin
is byte for byte the one these figures were taken at: `git diff --stat f7eaade4 7b489337 --
plugins/audit` prints nothing. Sections 1.5 and 1.6 decompose them, and they are the before-reading
of every target below. Arms A and B do not run the plugin, so their sessions stay the plain
references as long as the CLI version `pins.json` names is the one the after sessions run. If it is
not, they are run again.

**Step 1, offline.** Each task's micro-test (section 6). It costs nothing.

**Step 2, one single-task paid probe.** It runs once T1 to T4 and T7 to T10 have passed their
micro-tests.

- **Setup.** A copy of the single-task harness, `fixtures/bench-feature`, that changes
  `pins.json` → `pluginSha` and nothing else. Its arm C cell, `/audit:run P1.1`, runs once.
  `feature-C-1` is its before-reading, and `feature-A-1` and `feature-A-2` are its plain reference.
- **Expected cost.** About `0.64`, rung 1's single-task prediction with the Opus executor that
  harness's plan names (section 5.1). It is about `0.54` if G1 has been decided first. Its stop is
  `--max-budget-usd 1.5`.
- **What it confirms, each read with T1's rows:**
  - no `Read <plugin>/reference/` row;
  - the prefix the cycle's first request reads is at most 25000 tokens (T2);
  - the cycle's main-loop requests are at most 4 (T4);
  - the main-loop output per request is at most 500 tokens, which is section 5.3's doubled estimate;
  - no brief above 200 tokens among the largest outputs (T3);
  - the executor's first start written is at most 16000 tokens (T8);
  - the session is at most `0.75`.
- **What it does not confirm.** The per-task target. Its single task runs its executor on the plain
  session's own model, where rung 1 is predicted at 2.16 times plain and only G1 brings it under 2
  (section 5.1). A probe reading over a ceiling stops step 3 until the estimate behind it is
  re-derived and the prediction re-computed.

**Step 3, the full benchmark.** It runs only once the probe has passed.

- **Setup.** A copy of `<h2>` that changes `benchlib.EXPERIMENTS` and `pins.json` → `pluginSha`, and
  nothing else. That follows the harness's own precedent: v2 is "a copy of `../bench-feature/`
  extended, not an edit of it". A suggested name is `fixtures/bench-feature-cost`, and its records go
  to its own experiments folder. It runs arm C only: at least three sessions, as the protocol fixes
  per arm (`benchmark-feature-design.md`, section 6), in a seeded order, at the commit that lands the
  tasks. One study is enough for every target, because each target reads its own row of
  `stream-cost.py`.
- **Expected cost.** About `5.6` for the three: rung 1's predicted sessions, 1.7340 + 1.9347 + 1.9550.
  It is about `4.8` under G1: 1.4619 + 1.6584 + 1.6924. Re-run `python3 <h2>/estimate.py` before
  agreeing a budget, since it does not model this design.

**This study's protocol is the whole-feature benchmark's, and it lands with that benchmark's phase,
not with this one** (section 0). Until that phase merges, the sections cited here are read at
`a289dcbb`.

| Target | Row read per session | Rung 1 predicts |
|---|---|---|
| **the per-task ratio** | the cycle's billed cost (T1's cycle, main loop + its agents) ÷ `0.547004` | at most 2.0 in every session: 1.64 to 1.83. Under G1, the ideal is at most 1.25: 1.09 to 1.30 |
| **the whole-feature ratio** | `all models priced` ÷ `0.547004` and ÷ `0.843470` | 3.17 to 3.57, and 2.06 to 2.32 |
| **the phase overhead** | planning + sign-off + the close, less the project's own agents and fix tasks | at most `0.75` |
| T2 | the prefix the cycle's first request read, by origin; `Read <plugin>/reference/…` rows | no reference rows; prefix at most 50000 |
| T3 | inside the cycle, per task: briefs among its largest outputs, its main-loop output, its writes | none above 200; at most 1500 and 1500 |
| T4 | inside the cycle: main-loop requests per task, waves apart | at most 4, plus 2 a wave |
| T8 | each dispatch's start written | the first executor at most 16000 |
| T10 | sign-off's main-loop requests, a fix task apart | at most 4 |

**The value tests' readings** (section 5.4), for every after session:

- the open choices the plan names;
- the phase review's findings by severity, and whether any names the plan departing from the request;
- the phase gate's and invariants' verdicts;
- each fix task's decision and price;
- the hidden test `RefundAmounts.test_partial_returns_add_up_exactly`.

**What the earlier whole-set reading was, as dated history.** Before the cost target, the whole-set
reading was `all models priced` less planning's `$task`, set beside the earlier set's prediction. It
kept planning's reference reads and everything after the cycle, which that prediction did not
count. The whole-feature ratio replaces it. That ratio reads the session whole, and the phase
overhead is read apart with its own budget.

**Quality, so a saving cannot hide a loss.** For every after session, read beside the before sessions:

- `grade.txt`'s flags: hidden tests, scope, hallucination, claims and reuse;
- the plan readings the design fixes: phase status, each task's `tests.mode`, and whether the branch
  merged;
- `/audit:status --gate --fail-on invalid,invariant-breach,no-test-evidence`, run against that
  session's fixture.

A flag raised in an after session and in no before session is reported against the change and read by
hand.

**Confirm or refute.** A target is **confirmed** when every after session meets it, and **refuted**
when none does. Otherwise it is **inconclusive**, and the readings are shown side by side. With three
sessions, these are three observations, never a rate.

**Cost.** Step 2 and step 3 carry their expected costs above. `python3 <h2>/estimate.py` printed the
arm C range per session on 2026-10-07 (`benchmark-feature-design.md`, section 8). It does not model
this design's saving.

## 8. Decisions that are the user's

1. **Where the per-task intent check runs (C5, C14).** Rung 1 meets the per-task ceiling on the
   whole-feature sessions, 1.64 to 1.83 times plain. It meets neither the ideal there nor the
   ceiling for a single task whose executor shares plain's model, 2.16 on `feature-C-1`
   (section 5.1).
   - (a) Keep the review on every task. Rung 1 as predicted.
   - (b) G2: add `review.perTask: signals` with a default of `always` (minor). The review then runs
     only on R8's two computed conditions: a `redFirst` that did not come back `proved`, and a gate
     row that disagrees with the filed return. Never on the self-declared `task.risk` (C5,
     *Guarantees*). Predicted 1.26 to 1.47 on the whole-feature sessions.
   - (c) G1: add `review.perTask: phase` with a default of `always` (minor). The phase review binds
     every task's claim to its description, and sign-off refuses a phase with a task unbound.
     Predicted 1.09 to 1.30 on the whole-feature sessions, a mean of 1.19, and 1.81 on
     `feature-C-1`'s single task.
   - (d) Either of the above as the default: a major release (section 2).

   **Recommendation: (c), G1.** It is the only option that reaches the ideal on the arm's mean and the
   ceiling in the single-task shape. It also puts the check where its findings were acted on in every
   recorded case (section 1.6). The consequence to publish: a misread task is found before the merge,
   not before its commit, and repaired by a fix task. Keeping (a) is coherent if the per-task timing
   is wanted for itself. Then the ideal is out of reach, and so is the single-task ceiling with an
   executor on plain's model.
2. **The light path (C1).**
   - (a) Do not build it.
   - (b) Build it behind a key that defaults off. The README's enforced row then has to say it does not
     cover light-path work.
   - (c) Build it on by default (major).

   **Recommendation: (a).** C1 in section 3 predicts that its inline part costs more than it saves
   once C3 lands, and it is the one option that gives up an enforced row. Re-priced at rung 1's prefix
   with a hook holding the tool rule (C15), it still costs about `0.065` more a session.
3. **Where a filed return lives (C3).**
   - (a) The committed evidence directory, so an executor's claim is part of the record a clone
     receives.
   - (b) Session scratch under `stateDir`.

   **Recommendation: (a).** It is what lets a later checker compare a claim with its gate row. The cost
   is larger commits: in `feature-C-1` the hand-backs were 6142 and 3550 bytes (`largest outputs`).

   Either way the reviewer gains one write, through a write-once filing verb that derives its one
   path and never replaces a return already filed; the task id and role it files under are the
   caller's word (C3, *Guarantees*). Neither option touches the README's enforced row "the reviewer
   cannot edit", because the `tools:` line that holds it gains nothing. What (b) would add is that a
   stray reviewer write could not ride into the close commit with the evidence directory. Its trade
   is that the reviewer's findings then reach the record only through what the close writes.
4. **The spend on the confirming measurements.** The baseline is run and decomposed (sections 1.5 and
   1.6). What remains is the user's order (section 7):
   - the offline micro-tests, at no cost;
   - one single-task probe, about `0.64` (about `0.54` under G1), stopped at `1.5`;
   - the full benchmark's three arm C sessions, about `5.6` (about `4.8` under G1).

   **Recommendation:** agree both budgets now, so that step 3 is not waiting on a decision once
   step 2 passes.
5. **Main-loop TTL (C6a).** Whether the plugin can set it is **unknown**. The host facts name the
   settings and environment variables a user sets, and nothing says a plugin can ship one (section 9).
   Which TTL a user's main loop gets also follows their billing (section 1.4).
   - **Measured.** The longest gap between main-loop requests was 67 to 81 seconds in the three arm C
     sessions (the gap command). The one-hour write bought nothing there.
   - **Priced.** At five minutes, today's main-loop writes would have cost three eighths less:
     211809, 194155 and 216860 tokens × 3.0e-6 = `0.6354`, `0.5825` and `0.6506` (`cacheW1h` of the
     `plan`, `gate` and `close` rows). Under rung 1 the main loop writes 31265 to 41114 tokens in a
     session, an estimate (`P′` less what was cached, plus the cycle's 3000 and sign-off's 600 a
     request), so the difference falls to `0.094` to `0.123`.

   **Recommendation:** a doctor line prints this trade from a recorded session of the user's own: the
   longest main-loop gap, and what each TTL would have cost, computed as here (T12). Whether the usage
   ledger already holds the per-request times it needs is unchecked. The setting stays the user's.

## 9. Unknowns, and the choice that depends on each

Each is listed as not documented in the host facts gathered from the official documentation on
2026-10-07, except the one whose entry says otherwise:

- **Whether `${CLAUDE_PLUGIN_ROOT}` or `$ARGUMENTS` substitute inside a plugin command's `!`
  injection.** C2 and C8 use a tool call in its place, at the cost of one main-loop request. A probe
  would settle it: a scratch plugin command whose body holds an `!` line echoing both values, invoked
  once headless in a scratch directory. The session's first user message shows whether either was
  substituted. A probe is a paid session, so it was designed and not run. **Half of it is now
  measured:** in the command's body itself, the pinned CLI substituted `${CLAUDE_PLUGIN_ROOT}` at every
  occurrence (section 1.5.3). Inside an `!` line it is still unmeasured. The driver needs neither,
  because its loop runs `next` with a tool call.
- **Whether a plugin can ship a default `promptCacheTtl`.** C6a.
- **Which TTL a given user's main loop runs at.** The host facts document the default per billing:
  one hour on a subscription within its plan's included usage, five minutes on usage credits, an API
  key or a cloud provider. What the plugin cannot know is which applies to a user. Every dollar
  prediction here assumes one hour (section 1.4), and C6a is the difference.
- **Whether a plugin's agent can be spawned as a fork.** C6b, which is rejected on its guarantees
  either way.
- **The order of a subagent's initial context.** C6c. The documentation still does not give it. The
  sessions show its effect: a later dispatch reads 10109 or 8356 tokens of its start from cache
  (section 1.5.5).
- **Whether a command invoked several times injects its body each time.** **Measured** in
  `whole-C-3` and `whole-C-2-r`: yes, the whole body, after a one-line re-invocation notice (section
  1.5.3). Whether the model re-reads the reference files on a second command is answered for these
  sessions too: none re-read them. Under the driver the body is the loop, so a second injection costs
  the thin body.
- **Whether two `Agent` calls in one message run in the foreground.** `whole-C-3`'s wave came back as
  async launches, and the main loop spent two requests waiting (requests 22 and 23). Rung 1 counts
  those two per wave (section 5.1). A foreground wave would save them.

And from the records:

- **Single-task records only, before the whole-feature sessions.** Which requests are per task is
  read by the task cycle's bounds (section 1.1). The whole-feature sessions ran three tasks each, and
  their cycles held 22, 23 and 28 requests (section 1.5.4). Which of those were steps and which were
  one-offs is still inference from the calls. Retries after a permission refusal recurred in every
  session.
- **The divisor of 2.63 was calibrated on this prose.** Every target is in bytes, so the divisor moves
  only the dollar predictions.

## 10. Re-deriving every figure

| Figure | Command |
|---|---|
| stage, class, row and context figures | `python3 tools/stream-cost.py <record>/stream.jsonl` (`--json` for `requests` and `items`), from a checkout of `9501aa91`; the result-reading commit prints the same bytes for these sessions (section 0) |
| the arm C sessions' result events, main loop and pricing (section 6, T1) | `python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`, its header, `reconstruction:` and `pricing:` lines, from a checkout of the result-reading commit |
| what the CLI writes in each result event | the result command below; it reads the stream alone, so it needs no checkout |
| how each dispatch was launched, and how its last request in the stream ends | the dispatch command below; it reads the stream alone |
| bytes read first per entry, at a ref | `python3 tools/measure-context.py --ref 7b489337 --ref f7eaade4 --bytes-per-token 2.63`, from the same checkout |
| `/audit:task`'s entry total, until T1 adds the entry, from the same checkout | `python3 -c "import importlib.util as u; s=u.spec_from_file_location('mc','tools/measure-context.py'); m=u.module_from_spec(s); s.loader.exec_module(m); src,_=m.git_source('7b489337'); print(sum(r['bytes'] for r in m.entry_rows(src,'command','commands/task.md',None)))"` |
| the main loop's tool calls per request | the snippet in section 1.1 |
| the calls that bound planning and the task cycle, numbered by main-loop request | the event command below; it reads the stream alone, so it needs no checkout |
| the task cycle's figures, until T1 prints them, from the same checkout | the cycle command below, with the cycle's first and last request: `6 13` for `feature-C-1` |
| the rates | `git show 7b489337:plugins/audit/scripts/usage/_usage_core.py \| grep -n claude-opus-5-5` |
| bytes per heading of a reference or command file | below |
| the earlier backlog's state | section 0.1's commands, which read the working tree; their answers were taken at `7b489337` |
| an arm C session's spans, their billed figures, the main loop's context by origin, and each dispatch (sections 1.5.2 to 1.5.5) | the span command below, from a checkout of the result-reading commit |
| the billed cost of any run of main-loop requests and the agents they dispatched | the billed-span command below, with the first and last request, from the same checkout |
| the cycle's main-loop output by kind (section 1.5.4) | the output-kind command below, with the cycle's first and last request, from the same checkout |
| the command bodies a session received (section 1.5.3) | the injection command below; it reads the stream alone |
| the longest gap between main-loop requests (sections 1.4, 8) | the gap command below; it reads the stream alone |
| each dispatch's tool calls (section 1.5.5) | the agent-calls command below; it reads the stream alone |
| each arm C plan's intent answers and findings (section 1.6) | the findings command below, on the fixture `<x2>/<session>/run-meta.json` → `repo` names |
| the nine sessions' totals, requests, output pools and `$/request` (section 1.5.1) | `python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`, its `pricing:`, `contexts:` and `output pool` lines |
| rung 1, G2 and G1 (section 5.1) | the arithmetic written there, on the span command's readings |

```
python3 - <(git show 7b489337:plugins/audit/reference/orchestrator.md) <<'EOF'
import re, sys
L = open(sys.argv[1], encoding="utf-8").read().split("\n")
hs = [i for i, l in enumerate(L) if re.match(r"^#{1,3} ", l)]
print(sum(len(x.encode()) + 1 for x in L[:hs[0]]), "(before the first heading)")
for k, i in enumerate(hs):
    j = hs[k + 1] if k + 1 < len(hs) else len(L)
    print(sum(len(x.encode()) + 1 for x in L[i:j]), L[i])
EOF
```

For `execute-task.md`, at the same commit, sum the same expression over the line ranges section 3
names for C2's classes, as `L[a - 1:z]`.

The event command prints, for each main-loop request in stream order, every planning `Skill` call
and every `audit-task.py` verb with its operand. Section 1.1's bounds are read off its output. It is
a reading aid that matches the verb's text; T1 reads the call itself.

```
python3 - <record>/stream.jsonl <<'EOF'
import json, re, sys
n = {}
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    if e.get("type") != "assistant" or e.get("parent_tool_use_id"):
        continue
    i = n.setdefault(e["message"]["id"], len(n) + 1)
    for c in e["message"]["content"]:
        x = c.get("input") or {}
        if c.get("name") == "Skill":
            print(i, "Skill", x.get("skill"), x.get("args"))
        if c.get("name") == "Bash":
            for v in re.findall(r"audit-task\.py\"?\s+([a-z-]+(?:\s+[^\s;&|'\"-][^\s;&|'\"]*)?)",
                                x.get("command") or ""):
                print(i, "audit-task.py", v)
EOF
```

The cycle command takes a stream and the cycle's first and last request, and prices the cycle with
the pinned tool's own reading. It counts the cycle's requests and the agents they dispatched, and
it counts a main-loop cache entry for the request before the one that cached it. It prints the
cycle's bounds, its request count and output, its task-class tokens in the main loop, and its cost
by class.

```
python3 - <x>/feature-C-1/stream.jsonl 6 13 <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); lo, hi = int(sys.argv[2]), int(sys.argv[3])
ctx = dict((q["id"], q["context"]) for q in r["requests"])
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
cyc = set(q["id"] for q in main[lo - 1:hi])
made = dict((main[i]["id"], main[i - 1]["id"]) for i in range(1, len(main)))
sent = set(a for a, d in r["session"]["agents"].items() if d["request"] in cyc)
usd, tok = dict((k, 0.0) for k in sc.CLASSES), dict((k, 0.0) for k in sc.CLASSES)
for it in r["content"]["items"]:
    c = ctx[it["request"]]
    if (c == sc.MAIN and made.get(it["request"]) in cyc) or c in sent:
        usd[it["class"]] += it["writeUSD"] + it["carryUSD"]
        tok[it["class"]] += it["tokens"] if c == sc.MAIN else 0
for q in r["requests"]:
    if q["id"] in cyc or q["context"] in sent:
        cost, st = r["costs"][q["id"]], r["stages"][q["id"]]
        usd["task"] += cost["in"]
        for k, share in sc._output_class(q, st).items():
            usd[k] += (cost["out"] or 0.0) * share
print(main[lo - 1]["id"][-6:], main[hi - 1]["id"][-6:], len(cyc), round(sum(r["output"].get(i, 0) for i in cyc), 1))
print(dict((k, round(v, 1)) for k, v in tok.items()), dict((k, round(v, 6)) for k, v in usd.items()))
EOF
```

On `feature-C-1` it printed `eknkfg avGJjL 8 11374.0`, then task tokens `21857.0` and a cost of
task `0.704895`, file `0.212897`, run `0.0`. The cycle cannot hold an orient request: a request that
runs a plugin script is never in orient (`tools/stream-cost.py:337-338` at `9501aa91`), and the
cycle opens at one, with every later request after it. So the command charges every input it
counts to the task class, as the tool does outside orient.

The result command takes a stream. For each result event, in stream order, it prints the
stretch's number, the input side of the main-loop requests between that stretch's `init` event and
the next, and the result's own `usage`, as in, cacheW and cacheR. Then it prints whether
`modelUsage` and `total_cost_usd` are the same in every result.

```
python3 - <x2>/whole-C-3/stream.jsonl <<'EOF'
import json, sys
k, req, ends = -1, {}, []
F = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    if e.get("type") == "system" and e.get("subtype") == "init":
        k += 1
    elif e.get("type") == "result":
        ends.append(e)
    elif e.get("type") == "assistant" and not e.get("parent_tool_use_id"):
        v = [e["message"]["usage"].get(f) or 0 for f in F]
        s, old = req.get(e["message"]["id"], (k, [0, 0, 0]))
        req[e["message"]["id"]] = (s, [max(a, b) for a, b in zip(old, v)])
for i, r in enumerate(ends):
    print(i + 1, [sum(v[j] for s, v in req.values() if s == i) for j in range(3)], [r["usage"].get(f) for f in F])
print("same totals in every result:", len(set(json.dumps([r.get("modelUsage"), r.get("total_cost_usd")], sort_keys=True) for r in ends)) == 1)
EOF
```

On `whole-C-1`, `whole-C-3` and `whole-C-2-r` each line's two lists were equal, and the last line
read `True`.

The dispatch command takes a stream. For each `Agent` or `Task` call it prints the call's id
suffix, its `run_in_background`, the content types of the agent's last request in the stream, and
the start of the call's tool result.

```
python3 - <x2>/whole-C-3/stream.jsonl <<'EOF'
import json, sys
calls, last, back = {}, {}, {}
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    m, p = e.get("message") if isinstance(e.get("message"), dict) else {}, e.get("parent_tool_use_id")
    for c in m.get("content") if isinstance(m.get("content"), list) else []:
        if c.get("name") in ("Agent", "Task"):
            calls[c["id"]] = (c.get("input") or {}).get("run_in_background")
        if c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
            x = c.get("content")
            back[c["tool_use_id"]] = (x if isinstance(x, str) else "".join(t.get("text") or "" for t in x))[:34]
    if e.get("type") == "assistant" and p:
        last.setdefault(p, {}).setdefault(m["id"], set()).update(c.get("type") for c in m.get("content") or [])
for a, bg in calls.items():
    print(a[-6:], bg, sorted(list(last.get(a, {"-": set()}).values())[-1]), repr(back.get(a)))
EOF
```

On `whole-C-3` it printed `opKrv7` and `KRKraC` with `None`, `['text']` and
`'Async agent launched successfully.'`, and every other dispatch with `False`, `['tool_use']` and a
`[Subagent hand-back]` result.

The span command takes an arm C stream: a session with no `start` call has no cycle, and it stops
there with a traceback rather than printing a cycle of nothing. It finds the bounds by the verbs each
main-loop request calls, including a verb called through a variable that holds the script's path
(`whole-C-1` and `whole-C-2-r` call `$S done` and `$T add`). It prints each span's billed cost, main
loop and agents apart, with the main loop's requests, reads, writes and output. Then it prints the
main loop's context by origin: the prefix the cycle's first request read, what the cycle's requests
read, and each origin's write and carry over the session. Last, it prints one line per dispatch. A
write at the request after a `Skill` call that holds fewer bytes than a tenth of its tokens is booked
as a command body (section 1.5.7).

```
python3 - <x2>/<session>/stream.jsonl <<'EOF'
import importlib.util as u, re, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); ag = r["session"]["agents"]; cost = r["costs"]
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
def verbs(q):
    out = []
    for t in q["tools"]:
        x = t.get("input") or {}
        if t["name"] == "Skill" and (x.get("args") or "").split()[:1] == ["add"]: out.append(("add", ""))
        c = x.get("command") or ""
        out += re.findall(r"audit-task\.py\"?\s+([a-z-]+)(?:\s+([A-Z][\w.-]*))?", c)
        for v in re.findall(r"\b(\w+)=\"?[^\s;]*audit-task\.py", c):
            out += re.findall(r"\$\{?" + v + r"\}?\"?\s+([a-z-]+)(?:\s+([A-Z][\w.-]*))?", c)
    return out
V = [verbs(q) for q in main]
lo = next(i for i, v in enumerate(V) if any(a == "start" and b for a, b in v))
stop = next((i for i in range(lo, len(V)) if any(a in ("add", "add-phase") for a, b in V[i])), len(V))
hi = max(i for i in range(lo, stop) if any(a == "done" and b for a, b in V[i]))
plan = [i for i in range(lo) if any(a in ("add", "add-phase") for a, b in V[i])]
span = dict((q["id"], "cycle" if lo <= i <= hi else "after" if i > hi else "planning" if plan and i <= plan[-1] else "pre") for i, q in enumerate(main))
tasks = sorted(set(b for i in range(lo, hi + 1) for a, b in V[i] if a == "done" and b))
print("main requests", len(main), "| planning 1-%d, cycle %d-%d, tasks %s" % (plan[-1] + 1 if plan else 0, lo + 1, hi + 1, tasks))
row = {}
for q in r["requests"]:
    sp = span.get(q["id"]) if q["context"] == sc.MAIN else span.get(ag.get(q["context"], {}).get("request"), "unattributed")
    if q["context"] == sc.MAIN and q["reconstructed"]: sp = "unattributed"
    t = row.setdefault(sp, [0.0, 0.0, 0, 0, 0, 0.0]); who = 0 if q["context"] == sc.MAIN else 1
    t[who] += cost[q["id"]]["total"]
    if who == 0: t[2] += 1; t[3] += q["cr"]; t[4] += q["cw5"] + q["cw1"]; t[5] += (r["output"] or {}).get(q["id"], 0.0)
for sp in ("planning", "pre", "cycle", "after", "unattributed"):
    if sp in row: print("  %-12s main %.4f agents %.4f | main requests %d, read %d, written %d, output %.0f" % ((sp,) + tuple(row[sp])))
pos = dict((q["id"], i) for i, q in enumerate(main))
skill = set(main[i + 1]["id"] for i, q in enumerate(main[:-1]) if any(t["name"] == "Skill" for t in q["tools"]))
def origin(it):
    x = it["source"]
    if it.get("base"): return "cached before"
    if it["request"] in skill and it["tokens"] > 500 and it["bytes"] < 0.1 * it["tokens"]: return "command bodies"
    if x == "session start": return x
    if x.startswith("Read <plugin>/reference/"): return "reference prose"
    if x.startswith("Read <plugin>/commands/") or x == "Skill": return "command bodies"
    if x.startswith("hand-back"): return "hand-backs"
    if x.startswith("output:"): return "main-loop output"
    if it["class"] == "file": return "file reads"
    if x.startswith("Bash") and ("<plugin>" in x or "/scripts/" in x): return "plugin script output"
    return "other tool output"
at, cyc, whole = {}, {}, {}
for it in r["content"]["items"]:
    if it["request"] not in pos: continue
    o, j = origin(it), pos[it["request"]]
    whole[o] = whole.get(o, 0.0) + it["writeUSD"] + it["carryUSD"]
    if j <= lo - 1: at[o] = at.get(o, 0.0) + it["tokens"]
    n = sum(1 for k in range(j + (0 if it.get("base") else 1), len(main)) if lo <= k <= hi)
    cyc[o] = cyc.get(o, 0.0) + it["tokens"] * n
print("  origin                 prefix at cycle start   read in the cycle   write+carry, session")
for o in sorted(whole, key=lambda k: -whole[k]):
    print("  %-22s %9.0f %21.0f %19.4f" % (o, at.get(o, 0), cyc.get(o, 0), whole[o]))
for tid, a in ag.items():
    qs = [q for q in r["requests"] if q["context"] == tid]
    if a["context"] != sc.MAIN or not qs: continue
    f = [q for q in qs if not q["reconstructed"]][0]
    print("  dispatch at %d (%s) %s on %s: %d requests, start read %d, start written %d, %.4f" % (
        pos[a["request"]] + 1, span[a["request"]], a["type"], qs[0]["model"], len(qs), f["cr"], f["cw5"] + f["cw1"], sum(cost[q["id"]]["total"] for q in qs)))
EOF
```

On `whole-C-3`, `whole-C-1` and `whole-C-2-r` it printed the figures of sections 1.5.2 to 1.5.5. Run a
second time twenty seconds later, it printed byte-identical output on all three.

The billed-span command takes a stream and a first and last main-loop request. It prints the billed
cost of those requests and of every request of the agents they dispatched.

```
python3 - <x2>/<session>/stream.jsonl <first> <last> <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); lo, hi = int(sys.argv[2]), int(sys.argv[3])
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
ids = set(q["id"] for q in main[lo - 1:hi])
sent = set(t for t, a in r["session"]["agents"].items() if a["request"] in ids)
m = sum(r["costs"][q["id"]]["total"] for q in main[lo - 1:hi])
a = sum(r["costs"][q["id"]]["total"] for q in r["requests"] if q["context"] in sent)
print("requests %d-%d: main %.4f, agents %.4f, together %.4f" % (lo, hi, m, a, m + a))
EOF
```

On `whole-C-3` with `37 44`, `45 57` and `58 61` it printed `0.5580`, `0.9637` and `0.2428`: the fix
task, sign-off and the run's close.

The output-kind command takes a stream and a first and last main-loop request. It apportions each
request's measured output to briefs, shell commands, other calls and text by the bytes each emitted,
as the tool does, so it is an estimate.

```
python3 - <x2>/<session>/stream.jsonl <first> <last> <<'EOF'
import importlib.util as u, json, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); lo, hi = int(sys.argv[2]), int(sys.argv[3])
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
kind = {}
for q in main[lo - 1:hi]:
    b = {}
    for t in q["tools"]:
        x = t.get("input") or {}
        k = {"Agent": "brief", "Task": "brief", "Bash": "shell command"}.get(t["name"], "other call")
        v = x.get("prompt") if k == "brief" else x.get("command") if k == "shell command" else json.dumps(x)
        b[k] = b.get(k, 0) + len((v or "").encode())
    b["text"] = max(sc._emitted(q) - sum(b.values()), 0)
    out, n = (r["output"] or {}).get(q["id"], 0.0), float(sum(b.values())) or 1.0
    for k, v in b.items():
        kind[k] = kind.get(k, 0.0) + out * v / n
print(dict((k, round(v)) for k, v in sorted(kind.items())))
EOF
```

The injection command prints each user text block the main loop received, which is how a `Skill`
call's command body arrives, with its size in bytes and its first words.

```
python3 - <x2>/<session>/stream.jsonl <<'EOF'
import json, sys
# main-loop user text blocks (not tool results): their byte size and first words
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    if e.get("type") == "user" and not e.get("parent_tool_use_id"):
        c = (e.get("message") or {}).get("content")
        for b in (c if isinstance(c, list) else []):
            if b.get("type") == "text":
                t = b.get("text") or ""
                print(len(t.encode()), t[:48].replace("\n", " "))
EOF
```

The gap command prints the longest and second-longest gap between consecutive main-loop requests,
timed at each request's first event.

```
python3 - <x2>/<session>/stream.jsonl <<'EOF'
import json, sys, datetime
# longest gap between consecutive main-loop requests (first event of each message id)
seen, stamps = set(), []
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    if e.get("type") != "assistant" or e.get("parent_tool_use_id"):
        continue
    mid = e["message"]["id"]
    if mid in seen or not e.get("timestamp"):
        continue
    seen.add(mid)
    stamps.append(datetime.datetime.strptime(e["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
g = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
print(len(stamps), "requests; longest gap %.0f s, second %.0f s" % tuple(sorted(g)[-2:][::-1]))
EOF
```

On `whole-C-3`, `whole-C-1` and `whole-C-2-r` it printed 69, 67 and 81 seconds as the longest.

The agent-calls command prints every tool call each dispatched agent made, numbered by the agent's
own request.

```
python3 - <x2>/<session>/stream.jsonl <<'EOF'
import json, sys
calls, seen = {}, {}
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    m, p = e.get("message") if isinstance(e.get("message"), dict) else {}, e.get("parent_tool_use_id")
    if e.get("type") != "assistant":
        continue
    for c in m.get("content") or []:
        if not p and c.get("name") in ("Agent", "Task"):
            calls[c["id"]] = "%s#%d" % (c["input"].get("subagent_type"), len(calls) + 1)
        if p and c.get("type") == "tool_use":
            n = seen.setdefault(p, {}).setdefault(m["id"], len(seen[p]) + 1)
            x = c.get("input") or {}
            print(calls.get(p, "?"), n, c["name"], " ".join(str(x.get("command") or x.get("skill") or x.get("file_path") or "").split())[:60])
EOF
```

The findings command reads an arm C fixture's final plan, read-only. It prints each task's test mode
and intent answer, then each phase finding with its severity, its fix task and the start of its
resolution.

```
git -C <fixture> show main:docs/audit/audit-plan.json | python3 -c "import json,sys; m=json.load(sys.stdin); [print(t['id'], t['tests']['mode'], (t.get('intentCheck') or {}).get('answer')) for p in m['phases'] for t in p['tasks']]; [print(f['id'], f['severity'], f.get('fixTask'), f['resolution'][:50]) for p in m['phases'] for f in (p.get('review') or {}).get('findings') or []]"
```
