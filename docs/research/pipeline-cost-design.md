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

**Revised after its fourth review (2026-10-07).** Each correction sits in the section it concerns:

- The per-task ratio is printed on two plain figures. The cycle leaves out the plugin's
  session-level open and close, and whole arm A keeps plain's (section 0.2).
- G1 names every answer the per-task review returns. Each one is carried to the phase review, and
  the carrying is priced at sign-off (C14, sections 5.2 and 8).
- The main loop's writes are tied to its output. A filed return is written back once into its
  agent's cache (section 5.1).
- The sensitivity section doubles every estimate and adds G1 (section 5.3).
- Sign-off rests on readings wherever one exists (section 5.1).
- T1's phantom-final target is limited to the sessions its mechanism explains (section 6).

The figures this revision replaces are kept once, dated, beside the ones that replace them.

**Revised after its fifth review (2026-10-07).** The G1 and rung-1 holds are specified tightly
enough to build, each in the section it concerns. No earlier figure changes. Two derived ones are
added, both for the probe: G1's like-for-like output limit, and its writes bound under G1:

- The close's rule sits on `done` itself, in every form and under both keys, so a plain
  `done --commit` cannot skip what `--from-return` refuses (C3, section 5.2, T3, T6).
- The fix-task exception keys on the plan's own record, written when the fix task is added
  (section 5.2, T6).
- The key is read once per phase, and the plugin's merge path asks sign-off's question too
  (section 5.2, T6).
- The reviewer's definition, its return format with a per-task array, and the filing verb's
  phase-return shape are T6's files (C14, T6).
- The probe's stops say which reading they protect, and its writes check is given per rung
  (sections 5.3 and 7).
- The plugin's commit path is outside this repository's claims-block hook. T3's filed return
  carries the block, and the commit path appends it (T3).

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

- **The per-task ratio.** The task cycle's billed cost, divided by what arm A spent on the same
  tasks. The cycle is section 1.1's span: the main-loop requests from the first `start` to the last
  `done` before a request inside it plans, plus every request of the agents those requests
  dispatched. Arm A did the same tasks in one session, so dividing both sides by the tasks the
  cycle holds leaves the ratio unchanged.

  **The two sides do not hold the same kind of work unless the plain side is cut to match.** The
  cycle leaves out the plugin's session-level work: the session start is written in planning, and
  the closing report falls in the run's close (section 1.5.2). Whole arm A keeps plain's. Its first
  main-loop request writes the session start and lists the files, and its last writes the closing
  summary. In `whole-A-1`, `-2` and `-3` those two requests cost `0.079278`, `0.095520` and
  `0.087694`. That is 15.7, 15.9 and 16.4 percent of each session (the open-and-close command,
  section 10). So every per-task ratio here is printed both ways:

  - **like for like:** against arm A less its first and last main-loop requests, `0.459507`;
  - **against whole arm A:** `0.547004`, as the earlier revisions read it. This reading favours the
    plugin by the size of plain's open and close.

  This document takes the target to mean the like-for-like reading. It is the one in which each side
  holds its task work alone. Plain's open and close leave the plain side, as the plugin's leave the
  cycle for the phase overhead, which has a budget of its own. The other repair, adding the plugin's
  open and close to the cycle, would count that work under both targets. Which reading the target
  means is the user's to confirm (section 8, decision 1).
- **The whole-feature ratio.** The session's total, divided by arm A's mean and by arm B's mean.
  Arm B matched the plugin arm on every graded measure (the results document's section 4.6), so B
  is the price reference: what the plugin costs beyond B has to buy something measurable.

**The phase overhead** is everything in an arm C session outside the task cycle: planning, the
run's own preflight, sign-off with any fix task it runs, and the run's close.

**The plain figures.** Arm A's mean is `0.547004`, derived: (0.505336 + 0.600682 + 0.534995) / 3.
Arm B's mean is `0.843470`, derived: (0.764088 + 0.735201 + 1.031121) / 3. Each session's figure is
`all models priced` in `python3 tools/stream-cost.py <x2>/<session>/stream.jsonl`, which equals that
session's `total_cost_usd` (section 1.5.1). Arm A less its open and close is `0.459507`, derived:
(0.426059 + 0.505162 + 0.447301) / 3, each the open-and-close command's `the session less both`. The results document is
`docs/research/benchmark-feature-results.md`, which lands with the whole-feature benchmark phase: on
the day this was written it was at `186fcf7d` on that phase's branch and on neither this branch nor
`main`.

**Pins for the new readings.** Every figure in sections 1.5, 1.6 and 5 comes from the result-reading
commit's `stream-cost.py` (section 0), from its own report, or through section 10's commands. The
span, billed-span, output-kind, open-and-close, write-back and review commands call the tool's own
`analyse()`. The injection, gap and agent-calls commands read the stream alone. All of them read records that do not change.

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
| per task ÷ A less its open and close | 4.95 | 4.70 | 5.64 |
| sign-off: requests, cost | 45–57: `0.9637` | 35–37 and 44–48: `0.6367` | 43–52: `0.7891` |
| sign-off's fix task | 37–44: `0.5580` | 38–43: `0.3990` | none |
| the run's close | 58–61: `0.2428` | 49–52: `0.2457` | 53–55: `0.2005` |
| **phase overhead**, and ÷ A's mean | `3.3509`, 6.13 | `2.9071`, 5.31 | `3.0107`, 5.50 |

Derived: the cycle is its main loop, plus its agents, plus the fault's row. The per-task figure
is the cycle divided by three, and the ratio is the cycle divided by `0.547004`, or by `0.459507`
like for like (section 0.2). The phase overhead
is planning, preflight, sign-off, the fix task and the close. Cycle and overhead together equal each
session's total to the fourth decimal: 2.2755 + 3.3509 = 5.6264, 2.1614 + 2.9071 = 5.0685, and
2.5902 + 3.0107 = 5.6009. The executors' and reviewers' figures are the cycle's dispatches summed
(section 1.5.5), each taken unrounded, so a split can differ in its last digit from a sum of the
rounded dispatch lines. The span command prints the cycle's agents together: `0.7172`, `0.6572` and
`0.7920`.

Read off the table:

- **The task cycle is about four times arm A or more in every session, 3.95 to 4.74, and 4.70 to
  5.64 like for like.** The target is 2.
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
  per-task ratio would move by 0.026 at most if the row belonged elsewhere, or by 0.031 like for
  like, derived: 0.0142 / 0.547004 and 0.0142 / 0.459507.

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

The first draft left out the filing request. Its total was `0.3019`. The filing row still prices a
read alone. Filing also writes the return into the agent's cache once (C13). In `feature-C-1` that
is `0.0150` per task, derived: 6142 / 2.63 × 5.0e-6 + 3550 / 2.63 × 2.5e-6, from the two hand-backs'
bytes. This table leaves it out. Section 5.1's rungs count it, and section 5.5's dated history keeps
the table's figure.

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
- `done` holds the reviewer's half in every form that passes `--commit`, not in `--from-return`
  alone. At `7b489337`, `done` closes with `--commit <sha>` or with `--no-change --reason`, and
  either takes `--intent` and `--intent-basis` (`scripts/manifest/audit-task.py:38-43`). Its flag
  check, `_done_flags_refusal` (`:7010`), reads the flags and nothing else, so it cannot see a
  filed return. The rule therefore sits in `_locked_done`, before its call of `_done_task`
  (`:4750`). That is the only writer in the plugin's scripts that sets a task in a user's plan to
  `done` (`:4440`); the demo and benchmark builders write it only into plans they generate, and the
  panel edits a task's `model` and `skills` alone (`scripts/panel/_panel_settings.py:107`). T3's
  `--from-return` closes through the same function, so it meets the same rule.
  - A close that passes `--commit`, with or without `--from-return`, needs the reviewer's return
    for the task's current start, or `--intent not-asked` with its basis, which the verb already
    refuses without one (`:7055`).
  - When the reviewer's return is filed, its answer is the one recorded. A typed `--intent` word
    that differs from it is refused, `not-asked` included, so a typed word cannot replace an
    answer a reviewer filed.
  - `--from-return` also reads the executor's return for the current start.
  - It refuses, writing nothing, when a return it needs is not filed for the current start, and
    a return from an earlier start does not count.
  - A `--no-change` close has no diff to bind and keeps today's rule. Section 5.2 gives the rule
    under G1.

  The plain close is the reason. At `7b489337`, `done --commit <sha> --intent matches` closes with
  no review behind it, and `done --commit <sha>` with no `--intent` closes recording no answer at
  all. A rule on `--from-return` alone would leave both as the way past it.

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
    return under the wrong task, its own task is left with none, and `done` refuses that close in
    either form, by the cases T3 pins. The only way past that refusal is a close that records
    `--intent not-asked` with its basis.
  - **The reviewer runs nothing else that writes.** That stays a followed rule, as it is today: its
    Bash can write and nothing refuses it, which its own prompt says ("Nothing refuses these"). The
    filing verb widens what the reviewer is *told* it may do by one call. It does not widen what the
    harness lets it do.
  - **A close that skips the review reads no executor return either.** `--from-return` refuses
    without the executor's return, but a plain `done --commit` with `--intent not-asked` and its
    basis reads neither return. So a task can close with no executor claim filed, as any close can
    at `7b489337`. When the reviewer was handed its computed brief, a close that reads its return
    has an executor's behind it, because `brief` composes no reviewer brief before one is filed.
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
outside the contract. The close's refusal is wider: a `done --commit` with neither a filed reviewer
return nor `--intent not-asked` and its basis closes at `7b489337`, and is refused after T3. What a
verb refuses is outside the contract too, and `COMPATIBILITY.md`'s *Not promised* list records each
such change; its entry for `done` refusing a close over a verdict that no longer holds is the
precedent. T3 adds an entry for this one. The consequence to publish is that a close typed by hand,
with no review behind it, now has to say so: `--intent not-asked --intent-basis "<why>"`.

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
`audit-task.py` and the rule on its `done`, `commit-task-work.py`'s message, both agent prompts, the
task prose, `_refs.py`, `PLUGIN-BUILD-GUIDE.md` and `COMPATIBILITY.md`. The enforced and followed
tables lose no row, and the admissions that nothing checks a return's shape or its stamp are
answered by an exit code. The reviewer's prompt loosens by one call, held as above.

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
`1.5717`, `1.5157` and `1.8124` to `0.2292`, `0.2416` and `0.2191` (section 5.1, rung 1). Taken in
the order they would land, removing the prose saves `0.4859`, `0.4452` and `0.7345`. The driver with
its computed briefs and terse output then saves `0.8401`, `0.8159` and `0.8635` (section 5.1's
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
holds each of the driver's prints at the 300 bytes rung 1 assumes. With the hand-backs and the
output written back, that puts the cycle's write at 1555 tokens a task (section 5.1).

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
rung 1 that re-write costs 41358 × 4.0e-6 = `0.1654` in `whole-C-3`, against `0.054` saved on the
cycle's writes and output: 4664 × 4.0e-6 + 3500 × 10e-6. **Rejected: a cost of about `0.11`.**
The revision at `b72372f7` gave `0.047` and `0.12`, on writes of 3000.
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
  0.0042), the executor's and reviewer's `$/request` in `whole-C-3`'s `contexts:`.
- **What filing adds beyond the extra request.** Today an agent's return is its last output, and
  the agent makes no request after it, so the return is never written into the agent's own cache.
  Filed through C3's verb, the return is the input of a call, so the agent's hand-back request writes
  it into the agent's cache once, at the agent's write rate. Per session
  that is `0.0214`, `0.0205` and `0.0211` (section 5.1, *Agents*). `$/request` prices a further read
  and leaves this write out, and so did the revision at `b72372f7`. So the agents' net under rung 1
  is `+0.0398` to `+0.0452`, where that revision gave `+0.0187` to `+0.0248`.
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
  results document's section 4.4). So one review ran where three did. Saving: `0.2106` to `0.2193`
  per session over rung 1, in the cycle (section 5.1). A task it does not review gets none of the
  three answers listed under G1, and nothing carries them elsewhere.
- **Moved to the phase (G1).** No reviewer runs per task. Saving: `0.3072` to `0.3202` per session
  over rung 1, in the cycle (section 5.1). What the phase review then has to answer is everything
  the per-task review returns today, which is three answers, not one
  (`reference/execute-task.md:304-377` and `agents/audit-reviewer.md` at `7b489337`):
  - **the intent binding.** Does the diff do what the description asked, and does the executor's
    claim describe the diff? It is asked before the task commits. The reviewer prompt gives the
    reason it is asked per task: "the phase diff has no way back to the task that produced each
    line";
  - **the red-first grade.** The executor's `redFirst` word is echoed when its basis holds, and graded
    when it does not. A `not-proved` on a `tdd` task goes to a human;
  - **the inherited-test question.** Of the tests the task's own `tests.gate` selects, would any
    still pass with its behaviour deleted? It is bounded by `tests.gate`, which only a task-mode
    review is handed.

  A phase-mode review as written answers none of the three per task, and its own definition is
  what says so. In `mode: phase` it grades red-first `not-attempted`
  (`agents/audit-reviewer.md:55-57` at `7b489337`), and its return format holds one `intent` object
  for the whole phase (`:220-235`). With no `tests.gate`, its inherited-test answer is `not-asked`.
  So G1 changes the definition as well as the brief. The phase-mode paragraph asks the three
  questions of each task the brief lists, and the return gains a `tasks` array with one entry per
  task (T6). The brief carries each task's inputs (T3, T6). For each task it holds:
  - its commit SHA and declared files, so `git show <sha> -- <files>` reaches that task's own diff;
  - its description verbatim;
  - its filed return, with the `redFirst` word, the basis and `testsAdded`;
  - its recorded gate run;
  - its `tests.gate` commands, resolved.

  The brief asks the three questions of each task. What G1 still gives up is the timing. Each answer
  arrives before the merge instead of before the commit, so a `diverges` or a `not-proved` reaches a
  human at sign-off.

  **What carrying costs, at sign-off.** Each part is an estimate on a reading, from the review
  command (section 10):
  - the brief. Per task it holds what the main loop handed each per-task reviewer, the same
    inputs: 2373 to 4597 bytes, and 10842, 9457 and 9110 bytes per session. It is written once on
    the phase reviewer's Opus and read by that reviewer's four requests and the moved work's 9, 9
    and 8. For `whole-C-3`: 10842 / 2.63 × (5.0e-6 + 0.2e-6 × 13) = `0.0313`. The other sessions
    give `0.0273` and `0.0256`;
  - the work. This is what the three per-task reviewers spent beyond their starts: reading the
    diff, the test file and the code around it, and writing their answers. Re-priced at the phase
    reviewer's Opus rates it is `0.2042`, `0.2048` and `0.1996`;
  - the answers, written back once when the phase reviewer files its return. That is the per-task
    reviewers' hand-backs, 10322, 9655 and 10251 bytes, / 2.63 × 5.0e-6: `0.0196`, `0.0184` and
    `0.0195`.

  Together that is `0.2552`, `0.2505` and `0.2447`. It replaces the `0.0261` the revision at
  `b72372f7` gave, which priced three 1500-token returns read and nothing else. It is an upper
  estimate, because it assumes the phase reviewer reads each task's diff and code again. A phase
  reviewer that binds each claim from the phase diff it already reads pays less: the brief, the
  answers' output (5484, 5501 and 5432 tokens at 20e-6) and their write-back, `0.1532`, `0.1492`
  and `0.1482`.

  Carrying the two smaller answers costs little beyond the binding. The red-first grade is a reading
  of the filed return's word and basis. The inherited-test answer was `not-asked` in each of the
  nine per-task reviews (the review command), because each task's `tests.gate` was `["test"]`, a
  gate name that selects the whole suite (the findings command). The binding is the cost.

  So G1 does not remove the per-task review's work. It moves that work out of the cycle and into
  the phase overhead, where it runs on the phase reviewer's model. Over the whole session it saves
  `0.0641` to `0.0727` on the upper estimate and `0.1606` to `0.1739` on the lower (section 5.1).

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

- **The light path (C1)**, the main loop doing the task, costs about `1.02` against rung 1's `0.9768`
  in `whole-C-3`. This is an estimate:
  - A's mean work, `0.547004`;
  - the larger prefix it reads, about 3.3 requests a task (A's 9 to 11 over three tasks) × [3 ×
    (41358 − 16607) + 15000 × (0 + 1 + 2)] × 0.2e-6 = `0.0787`. Here 16607 is `whole-A-1`'s first
    read and write (11891 + 4716), and 15000 is an estimate of the work a task leaves;
  - the driver's requests without the executor's dispatch, 11 of them, with their writes tied to
    their output as section 5.1 ties them, 2750 + 924 = 3674:
    0.2e-6 × (11 × 41358 + 3674 × 5) + 3674 × 8.0e-6 + 2750 × 20e-6 = `0.1791`;
  - the reviewers, `0.2063`, and their returns written back when filed, `0.0098` (section 5.1).

  The revision at `b72372f7` gave about `1.00` against `0.9400`, on writes of 3000.

  The executors run on Sonnet and the main loop on Opus, so the work costs more inline.
- **A forked reviewer (C6b)** reads the main prefix on Opus: 3 × 43690 × 0.2e-6 + 9000 × 5.0e-6 +
  2000 × 20e-6 = `0.1112` per review, against a Sonnet review at about `0.065`. It costs `0.046` more
  per task. 43690 is the prefix halfway through rung 1's cycle, 41358 + 4664 / 2 (section 5.1). The
  revision at `b72372f7` read 45358, sign-off's flat estimate then, and gave `0.1122` and `0.047`.

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
| C9 step driver, with C2, C3, C8 and C10 as its parts | cycle main loop `1.5157`–`1.8124` → `0.2191`–`0.2416` | none | **recommended** (rung 1) |
| C10 terse output | `0.0051`–`0.0176` in the cycle after C9; it holds C9's per-task write | none | **recommended**, inside C9 |
| C11 one executor per phase | `−0.0468` (a cost, `whole-C-3`) | per-task isolation and the parallel wave lost | rejected |
| C12 cheaper main-loop model | about `−0.11` (a cost, `whole-C-3`) | unmeasured decision quality | rejected |
| C13 trimmed agent prompts | `0.0406`–`0.0467` | none | **recommended** (rung 1) |
| C13 `omitClaudeMd` / skills / agent TTL 1h | about `0.02` / `0` / `−0.2396` | the project's rules / none / none | rejected / not taken / rejected |
| C14 per-task review gated (G2) | `0.2106`–`0.2193` over rung 1, in the cycle | an unreviewed task gets none of the per-task review's three answers | the user's (section 8) |
| C14 per-task review at the phase (G1) | `0.3072`–`0.3202` over rung 1 in the cycle, of which `0.1482`–`0.2552` is paid again at sign-off for carrying the review there | the intent binding, the red-first grade and the inherited-test question each move from before the commit to before the merge, carried in the phase review's brief | the user's (section 8) |
| C15 light path or fork reviewer, with a hook holding the tool rule | about `−0.044` a session / `−0.046` a task (costs) | input isolation lost | rejected |

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
- **Output**, 250 tokens a request, so `O` = 3500. The run's own preflight requests, each one short
  script call, emitted 242 tokens on average, derived: (415 + 477 + 318) / 5, the span command's
  `pre` rows.
- **Writes, tied to the output.** Inside the cycle every request's output enters the main loop's
  cache at the next request, the rule section 1.1 states for a row. So `W` = `O` + `T`, where `T`
  is the tool results the cycle receives. Per task that is two one-line hand-backs of 80 tokens
  (C3's estimate) and two `next` prints at T4's ceiling of 300 bytes, 114 tokens each. So `T` = 3 ×
  (2 × 80 + 2 × 114) = 1164, and `W` = 3500 + 1164 = `4664`, which is 1555 a task. The revision at
  `b72372f7` set `W` = 3000, below `O`, which none of the readings below allows.

  The write-back command (section 10) reads how much of the cycle's output came back as the loop's
  own cache writes: 0.97, 1.02 and 1.32 in `whole-C-3`, `whole-C-1` and `whole-C-2-r`. Readings
  above 1 hold background agents' reports. These arrive as notifications the tool does not size, so
  it books them as the loop's own output. `whole-C-3`'s two waits, requests 22 and 23, emitted 183
  tokens and wrote back 4251 that way (the same command on `22 23`). That the other two sessions'
  excess has the same cause is inference. Arm A's whole sessions read 0.79 to 0.86, lower because a
  session's last output is never written back.
- **Agents**: today's cycle agents, net of the fault's row, plus C3's extra requests (`0.0654`) less
  the prompt trims (`0.0429`, `0.0406`, `0.0467`), from C13. Then each filed return is written back
  once, at the agent's write rate (C13). The returns are estimates on readings (the review command,
  section 10):
  - an executor's return is taken at its session's first executor's hand-back, 4054, 3954 and 3979
    bytes, because the wave's two came back as notifications the tool does not size;
  - the reviewers' are their own hand-backs, 10322, 9655 and 10251 bytes for the three.

  For `whole-C-3`: (3 × 4054 + 10322) / 2.63 × 2.5e-6 = `0.0214`. The others are `0.0205` and
  `0.0211`.
- **Planning** writes everything the cycle then reads, `P′` less what was cached before the session,
  at `w`. Its five requests (an estimate: invoke, read the code over two requests, write the plan
  file, one batch `add`) read halfway between the cached start and `P′` on average. Its output is
  what today's planning typed, since the plan's text is the irreducible part. The project's explorer
  is kept as recorded.
- **Sign-off** takes 4 requests, plus 3 per fix task, an estimate and T10's target:
  - the four are the phase reviewer's dispatch, the triage decision, the sign-off step and the final
    report;
  - a fix task's three are `next`, the executor and `next`, and the recorded fix tasks closed
    `not-asked`. Under G1 a fix task keeps that close only as the `fixTask` its finding records
    (section 5.2). Closed `deferred`, it would need a second phase review this model does not price;
  - it starts at the prefix the cycle leaves, `P′` + `W`, and grows by its own writes, so its main
    loop is `main(S, P′ + W, W_s, O_s)`. That replaces the flat `P′` + 4000 a request the revision at
    `b72372f7` assumed;
  - its output `O_s` is 250 a request, as in the cycle, an estimate. The exception is the final
    report, which is a reading: 1898, 1729 and 1722 tokens, each session's last main-loop request
    (the open-and-close command). An estimate of 1000 stood there;
  - its writes `W_s` are tied as the cycle's are. They are every output but the report's, plus the
    reviewer's one-line hand-back, the final step's print and the triage print. The triage print
    lists the review's findings, so it is taken at the phase reviewer's whole hand-back, 5404, 4610
    and 4325 bytes / 2.63, an upper reading. A fix task adds its three outputs, a hand-back and two
    prints. This replaces 600 a request;
  - the agents are the project's reviewer as recorded, its filing request, and the fix executor as
    recorded. The filing request is the reviewer's `$/request` at sign-off (`contexts:`, `0.0038`,
    `0.0038` and `0.0034`), plus its return written back once at 5.0e-6. That is `0.0141`, `0.0125`
    and `0.0116` in all, where an estimate of `0.005` stood;
  - the fix executor's own C3 requests and trim are left out. On `whole-C-3`'s they nearly cancel:
    2 × 0.0047 + 3153 / 2.63 × 2.5e-6 = `0.0124`, against 3722 × (2.5e-6 + 0.2e-6 × 3) = `0.0115`.

  The model prices one phase review at what the recorded one cost. In these sessions the plugin's
  review step and the project's own rule 5 merged into one review. Whether they still do under the
  driver is unmeasured, and T11's probe reads it. Section 5.4 doubles sign-off's estimates against
  its budget.

Written out for `whole-C-3`:

- cycle main loop: 0.2e-6 × (14 × 41358 + 4664 × 13 / 2) + 8.0e-6 × 4664 + 20e-6 × 3500
  = 0.1219 + 0.0373 + 0.0700 = `0.2292`;
- cycle agents: 0.5219 + 0.1953 − 0.0134 + 0.0654 − 0.0429 = `0.7263`, and the filed returns
  `0.0214`;
- cycle: `0.9768`, which is 2.13 times A less its open and close, and 1.79 times A's mean;
- planning: 0.2e-6 × 5 × (10950 + 41358) / 2 + 8.0e-6 × (41358 − 10950) + 20e-6 × 6467
  = 0.0262 + 0.2433 + 0.1293 = `0.3988`;
- sign-off, with its fix task, at `S` = 7: `W_s` = 6 × 250 + 80 + 2055 + 114 + (114 + 80 + 114) =
  4057 and `O_s` = 6 × 250 + 1898 = 3398. So `main(7, 46022, 4057, 3398)` = 0.0669 + 0.0325 +
  0.0680 = `0.1673`, and + 0.1715 + 0.0141 + 0.0666 = `0.4194`;
- whole: 0.3988 + 0.9768 + 0.4194 = `1.7950`, which is 3.28 times A's mean and 2.13 times B's.

The other two sessions are the same arithmetic on their own readings.

**G2, the per-task review on computed signals**, runs one review where the sessions ran three
(C14). A task with no review takes two requests: dispatch the executor, then `next`. So
`k` = 4 + 2 × 2 + 2 = 10 and `O` = 2500. `T` = 388 + 2 × 194 = 776, so `W` = 3276. The agents are the
executors, a third of the reviewers, C3's extra requests for three executors and one reviewer, less
the trims on the requests that remain, and those four returns written back.

**G1, the per-task review at the phase**, gives `k` = 2 × 3 + 2 = 8, `O` = 2000, `T` = 3 × 194 = 582
and `W` = 2582. The agents are the executors with their extra requests, less their trim, and their
returns written back. Sign-off gains what carrying the per-task review costs: `0.2552`, `0.2505` and
`0.2447` on C14's upper estimate. On C14's lower estimate it gains `0.1532`, `0.1492` and `0.1482`.

| Rung | Guarantee | Per-task ratio, like for like: `whole-C-3` / `-C-1` / `-C-2-r`; mean | Per-task ratio ÷ whole A | Whole ÷ A's mean | Whole ÷ B's mean |
|---|---|---|---|---|---|
| 0, today, measured | as today | 4.95 / 4.70 / 5.64; 5.10 | 4.16 / 3.95 / 4.74; 4.28 | 10.29 / 9.27 / 10.24; 9.93 | 6.67 / 6.01 / 6.64; 6.44 |
| 1 | **no change** | **2.13 / 2.03 / 2.26; 2.14** | 1.79 / 1.70 / 1.90; 1.80 | 3.28 / 3.63 / 3.68; 3.53 | 2.13 / 2.36 / 2.38; 2.29 |
| 1 + G2 | an unreviewed task gets none of the per-task review's three answers | 1.65 / 1.55 / 1.80; 1.67 | 1.39 / 1.30 / 1.51; 1.40 | 2.88 / 3.23 / 3.29; 3.13 | 1.87 / 2.09 / 2.13; 2.03 |
| 1 + G1 | the per-task review's three answers move to before the merge, carried in the phase review's brief | **1.44 / 1.33 / 1.59; 1.45** | 1.21 / 1.12 / 1.33; 1.22 | 3.16 / 3.50 / 3.56; 3.41 | 2.05 / 2.27 / 2.31; 2.21 |
| 1 + G1, the carried review charged to the cycle | as G1 | 1.99 / 1.88 / 2.12; 2.00 | 1.67 / 1.58 / 1.78; 1.68 | as G1 | as G1 |

Each ratio is derived: the predicted cycle or session divided by `0.459507`, `0.547004` or
`0.843470`. G1's sessions and its last row take C14's upper estimate of the carrying. On the lower
estimate the last row is 1.77 / 1.66 / 1.91; 1.78 like for like and 1.49 / 1.39 / 1.60; 1.49 ÷
whole A, and G1's sessions are 2.98 / 3.32 / 3.38 ÷ A's mean and 1.93 / 2.15 / 2.19 ÷ B's. The last
row is not the per-task ratio as section 0.2 defines it, because the phase review runs after the
cycle. It is printed because G1 saves its cycle cost by moving the work there, and the ratio alone
would not show the move. The predicted cycles are:

- rung 1: `0.9768`, `0.9326`, `1.0368`;
- G2: `0.7600`, `0.7133`, `0.8262`;
- G1: `0.6602`, `0.6124`, `0.7296`, and with the carried review `0.9154`, `0.8629`, `0.9744`.

The predicted sessions are:

- rung 1: `1.7950`, `1.9874`, `2.0105`;
- G2: `1.5762`, `1.7662`, `1.7989`;
- G1: `1.7306`, `1.9147`, `1.9464`.

Rung 0's mean is the measured cycles' mean, 2.3424 / 0.459507 and 2.3424 / 0.547004. The revision at
`b72372f7` gave rung 1 1.72 / 1.64 / 1.83 and G1 1.17 / 1.09 / 1.30, against whole arm A only. It
had writes below output, sign-off on estimates, and G1 carrying nothing but three returns read.

**Where each rung-1 saving comes from**, taken in the order the tasks would land, on the cycle's
modelled main loop:

| | `whole-C-3` | `whole-C-1` | `whole-C-2-r` |
|---|---|---|---|
| modelled today | `1.5552` | `1.5027` | `1.8171` |
| the prose leaves the prefix (C2, C4, C8) | `−0.4859` | `−0.4452` | `−0.7345` |
| the driver with computed briefs and terse output (C9, C3, C10) | `−0.8401` | `−0.8159` | `−0.8635` |
| rung 1's cycle main loop | `0.2292` | `0.2416` | `0.2191` |
| agents: C3's requests and filed returns, less C13's trims | `+0.0439` | `+0.0452` | `+0.0398` |

The prose step is `main(k, P − prose − bodies + 4500, W, O)` at today's `k`, `W` and `O`. The
driver step then sets `k` and `O` to rung 1's, ties `W` to `O`, and removes nine tenths of the script
output.

**Rejected rungs, priced** (section 3):

| Option | Effect on the cycle | Guarantee given up |
|---|---|---|
| one executor per phase (C11) | `+0.0468`, a cost | per-task input isolation, the parallel wave |
| a cheaper main-loop model (C12) | about `+0.11`, a cost | none in the tables; decision quality unmeasured |
| the light path with a hook (C15) | about `+0.044`, a cost | input isolation |
| a forked reviewer with a hook (C15) | `+0.046` a task, a cost | input isolation, `phase.review.model` |
| `omitClaudeMd` (C13) | about `−0.02` | none in the tables; it drops the project's rules |
| a one-hour agent cache (C13) | `+0.2396`, a cost | none |

**The single-task shape**, for continuity with section 5.5's earlier set, on `feature-C-1`. Plain
there is `0.298019`, derived: (0.284359 + 0.311679) / 2 (the analysis, section 3). Today's session
is 5.87 times that, and the earlier set predicted 3.37 (1.0047 / 0.298019).

- **Rung 1 with the recorded Opus executor**: `0.6625`, which is 2.22 times plain.
  - The main loop is `0.1656`. That is five requests at a prefix of 22695 tokens: 11891 cached, 9304
    written and 1500 of thin body.
  - Its writes are tied as in the ladder, 4 × 250 + 388 = 1388. Its output is 4 × 250 + 1239. The
    1239 is the report request `feature-C-1` recorded (`FSeULu`, the open-and-close command's
    `last`).
  - The agents are `0.4819`: the executor `0.3998`, the reviewer `0.0957`, `0.0226` of C3's
    requests, less `0.0362` of trims.
  - The two returns written back add `0.0151`, derived: 6142 / 2.63 × 5.0e-6 + 3550 / 2.63 × 2.5e-6.
- **Rung 1 with the executor's own tokens priced on the Sonnet row**: `0.4841`, which is 1.62 times
  plain. The executor would cost `0.2179`: 31513 × 2.5e-6 + 180263 × 0.2e-6 + 10306 × 10e-6. Its
  trim is then `0.0160`, not `0.0253`, and its return is written back at 2.5e-6.
- **Rung 1 + G1**: the main loop makes four requests, with `W` = 3 × 250 + 194 = 944 and `O` = 3 ×
  250 + 1239, which is `0.1522`. The agents are the executor, its two requests and its trim:
  0.3998 + 0.0126 − 0.0253. Its return written back adds `0.0117`. That gives `0.5510`, 1.85 times
  plain, with the Opus executor. With Sonnet it is `0.3725`, 1.25 times plain.
- **What G1 defers in this shape.** `/audit:run` runs no phase review, so the task's three answers
  wait for a later sign-off. Priced as C14 prices them, they come to `0.1183`:
  - the reviewer's brief, 4742 / 2.63 × (5.0e-6 + 0.2e-6 × 8) = `0.0119`;
  - its work beyond its start at Opus rates, `0.0996`;
  - its answers written back, 3550 / 2.63 × 5.0e-6 = `0.0067`.

  These are the review command's readings. Charged back, G1 with the Opus executor is `0.6693`,
  2.25 times plain, above rung 1's 2.22, because the moved review runs on Opus where the per-task one
  ran on Sonnet.

The revision at `b72372f7` gave `0.6444` (2.16), `0.4718` (1.58), `0.5401` (1.81) and `0.3675` (1.23).
It had writes below output, a report of 1000 tokens and no returns written back.

An isolated executor on the same model as plain already cost 1.34 times plain on its own (0.3998 /
0.298019). It pays a start, a brief and a return on top of the work. So which model the plan gives
a task's executor moves the per-task ratio as much as any rung does. The arm C plans gave every task
Sonnet (the results document's section 2.3).

### 5.2 The recommended set

**Rung 1: the main loop keeps the decisions, and a script performs every step that needs none.** It
hands the model what it needs by path, prints each rule at the step it applies to, and asks every
judgement as a named decision. That is C9, with C2, C3, C4, C8 and C10 as its parts, the agent half
of C13, the planning batch and sign-off as one step. Section 6 has its tasks T1 to T4 and T7 to T10.

**Like for like it does not meet the per-task ceiling in any recorded whole-feature session**:
2.03 to 2.26 times plain, a mean of 2.14. Against whole arm A it does meet it, at 1.70 to 1.90, a
mean of 1.80. That is the reading earlier revisions stated, and it favours the plugin by plain's
open and close (section 0.2). Those plans gave every executor Sonnet. **In the single-task shape
with an executor on the plain session's own model it does not meet the ceiling either:** 2.22 times
plain on `feature-C-1`, a whole session against whole plain sessions. G1 brings that to 1.85, but
2.25 once the review it defers is charged back (section 5.1).

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
| the per-task review's three answers: the intent binding, the red-first grade, the inherited-test question (C14) | the reviewer's dispatch, followed | the driver printing the dispatch; `done` refusing every close that passes `--commit`, in either form, without the reviewer's filed return or `--intent not-asked` with a basis (C3) |
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

**The ceiling like for like, and the ideal on either reading, need more than rung 1. The one
guarantee change on offer is the user's decision** (section 8, decision 1):

- **G1, the per-task review at the phase.** Like for like it is 1.33 to 1.59, a mean of 1.45. That
  meets the ceiling in every session and the ideal in none. Against whole arm A it is 1.12 to 1.33,
  a mean of 1.22. That is under 1.25 on the mean, in `whole-C-3` and in `whole-C-1`, and over it in
  `whole-C-2-r`. On that reading the mean's margin is `0.0163` of cycle cost, and doubling any one
  of four estimates removes it (section 5.3). G1 reaches these figures by moving the per-task
  review's work to sign-off, where carrying the three answers costs `0.1482` to `0.2552` a session
  (C14). Charged back to the cycle, G1 is 1.66 to 2.12 like for like and 1.39 to 1.78 against whole
  arm A.
- **G2, gated on computed signals.** Like for like it is 1.55 to 1.80, a mean of 1.67. Against whole
  arm A it is 1.30 to 1.51, a mean of 1.40. It meets the ceiling on both readings and the ideal on
  neither. It carries nothing, so the two tasks it does not review get none of the three answers.

**No option here reaches the ideal like for like.** The closest is G1 at a mean of 1.45, and the gap
to 1.25 is `0.0930` of cycle cost on the mean, derived: 0.6674 − 1.25 × 0.459507.

**Recommendation for the decision: G1, carrying all three answers.** It keeps every answer the
per-task review gives today, each still bound to its own task's commit, and gives up only their
timing. It puts the check where its result was consumed. In both sessions where a per-task review
found something, the task was committed in the same request, and the finding was acted on at the
phase (section 1.6). G2 gives answers up instead of moving them. Its trigger fired on the
command-line task in every session, because the red-first helper cannot classify an `argparse` exit
(the results document's section 4.4). It measures the helper's limit, not the task's risk.

The facts about G1 that are not reasons for it: over the whole session it saves `0.0641` to `0.1739`
against rung 1, and G2 saves `0.2117` to `0.2212` (section 5.1's sessions). The work G1 moves lands in
the phase overhead, which it takes over its budget (section 5.4).

**G1's guarantee change, and how it is held instead.** Today the per-task review returns three
answers before the task commits: the intent binding, the red-first grade and the inherited-test
question (C14). Under G1 each one is answered before the phase merges.

- **Carried by:** the phase reviewer's computed brief (T3, T6), and the reviewer's own definition,
  whose phase-mode paragraph and return format T6 changes so that it answers each task in a `tasks`
  array. For each task the brief holds the commit SHA and files, the description verbatim, the
  filed return with its `redFirst` word and basis, the recorded run and the `tests.gate` commands,
  and it asks the three questions of each task. The SHA is the way back from a line to its task,
  which the reviewer prompt says the phase diff lacks (`agents/audit-reviewer.md:48` at `7b489337`).
- **Held by:** a close state of its own, and one refusal asked at sign-off and again at the
  plugin's merge. Each reads the plan's own record, never a flag the caller sets at the close.
  - *The close.* The rule sits on `done` itself, in the check C3 places in `_locked_done`, so it
    holds whichever form closes the task. Under `review.perTask: phase`, every close that passes
    `--commit`, with or without `--from-return`, records the task's intent as `deferred` itself,
    and refuses any `--intent` word, `not-asked` included, writing nothing. So a task with a diff
    can close neither as `not-asked`, the word sign-off already counts as answered
    (`reference/execute-task.md:373-377`), nor as a `matches` no reviewer gave. `deferred` is a word
    the verb writes and never one `--intent` offers (`INTENT_ANSWERS`,
    `scripts/manifest/audit-task.py:4318`), so no caller can type it.
  - *The one exception, a fix task the plan records as one.* A task that a finding in its own
    phase's `review.findings` names as its `fixTask` may close `--intent not-asked` with its basis,
    which is how section 5.1's sign-off model closes a fix task. Every other word is refused for it
    too, and with no `--intent` it records `deferred` like any task. At `7b489337` no fix task could
    meet this at its own close: `fixTask` is written only by `resolve-finding`, which refuses until
    the fix task is `done` (`audit-task.py:7676`). So T6 has `add` write `fixTask` onto the
    findings a new task fixes, in the write that adds the task, and nowhere else. It refuses a
    finding outside the task's phase, or one already naming another task. A task added before its
    finding existed, which is every task the phase review answers for, cannot gain the link. A
    finding holding `fixTask` with no `commit` is already a state the plan holds after a `reopen`
    (`:4955-4958`), and the findings tally counts only the two together (`:7348`).
  - *The key, read once per phase.* `start` records the key's value on the phase when it promotes
    the phase's first task, and `done` and the driver read the phase's value, never the live key.
    Read live, a key switched to `always` partway through would let a later task close `not-asked`
    with a basis, which `always` accepts, and the refusal below reads only tasks closed `deferred`.
  - *The refusal.* The sign-off verb refuses, writing nothing, while any task closed `deferred`
    lacks any of its three answers in the phase review's filed return. `close-phase.py` asks the
    same question through the same function before it merges or hands over the merge command. At
    `7b489337` it refuses on the gate verdict, and its merge plan reads the trees and the branches
    and never whether sign-off passed (`scripts/git/_worktrees.py:722`). Without the question, the
    plugin's own merge would be a way past the sign-off verb.
  - *Followed, not enforced:*
    - a `--no-change` close of a task whose files did change. It records no commit, so there is no
      diff for `deferred` to hold, and nothing compares the task's files with what changed while it
      ran. `not-asked` with its basis keeps its meaning there, as today;
    - a `cancel` of a task whose work landed, which records its reason and no answer, as today;
    - a hand edit of the shard. `journal-writes.py` records every write to the plan after the fact,
      and nothing refuses one (`reference/phase-signoff.md:69`). That is every plan field's standing
      today;
    - a merge made outside the plugin, by hand or through a pull request.

  T6 pins each enforced half with a fixture whose tasks closed the G1 way.
- **Given up:** the timing, and nothing else the per-task review returns. A misread task, a
  `not-proved` on a `tdd` task or a vacuous inherited test is found after its commit, not before.
  Its repair is a fix task inside the phase, as both recorded per-task findings already were, rather
  than a re-spawn before the commit.
- **The consequence to publish:** that timing. A key with a default of `always` keeps today's
  behaviour. A default of `phase` would be a major release (section 2).

### 5.3 How far the margin can be trusted

Every estimate the cycle rests on is doubled here, first one at a time and then together. Each
figure is section 5.1's model run with that one input doubled, with the writes tied to the output as
section 5.1 ties them. Doubling the output therefore raises the writes by the same amount. A doubled
request count adds each new request's output, its write-back and one print. The phase overhead's
estimates are doubled in section 5.4.

**Rung 1 against the 2.0 ceiling**, in `whole-C-2-r`, its worst session. There it is 1.90 against
whole arm A and 2.26 like for like, so like for like it is over the ceiling before anything
doubles. Against whole arm A the margin is 2 × 0.547004 − 1.0368 = `0.0572` of cycle cost.

| Estimate | Value | Doubled | Added to the cycle | Ratio then, ÷ whole A | like for like |
|---|---|---|---|---|---|
| output per request, writes tied | 250 tokens | 500 | `0.1025` | 2.08 | 2.48 |
| requests per task | 4 | 8 | `0.2021` | 2.26 | 2.70 |
| tool results per task | 388 tokens | 776 | `0.0108` | 1.92 | 2.28 |
| thin bodies | 4500 tokens | 9000 | `0.0126` | 1.92 | 2.28 |
| the wave's waits | 2 | 4 | `0.0308` | 1.95 | 2.32 |
| script output left by terse output | a tenth | a fifth | `0.0006` | 1.90 | 2.26 |
| trimmed prompts | 9000 and 7000 bytes | 18000 and 14000 | `0.0414` | 1.97 | 2.35 |
| filed returns | section 5.1's sizes | twice | `0.0211` | 1.93 | 2.30 |
| output and requests together | | | `0.4003` | 2.63 | 3.13 |
| every row at once | | | `0.5505` | 2.90 | 3.45 |

Doubling the output alone, or the requests alone, takes `whole-C-2-r` over the ceiling on the whole-A
reading too. The revision at `b72372f7` said any one estimate could double and the worst session
would stay under the ceiling. Its requests row went from 4 to 5 rather than to 8, and its writes did
not follow its output.

**G1 against the 1.25 ideal**, on the arm's mean, where the claim was made, and in `whole-C-2-r`.
Like for like the mean is 1.45 before anything doubles, so there the table shows only how far the
ideal is. Against whole arm A the mean's margin is 1.25 × 0.547004 − 0.6674 = `0.0163`.

| Estimate | Value | Doubled | Added, mean | Mean ÷ whole A | Mean like for like | `whole-C-2-r` ÷ whole A | `whole-C-2-r` like for like |
|---|---|---|---|---|---|---|---|
| as predicted | | | | 1.22 | 1.45 | 1.33 | 1.59 |
| output per request, writes tied | 250 tokens | 500 | `0.0574` | 1.33 | 1.58 | 1.44 | 1.71 |
| requests per task | 2 | 4 | `0.1018` | 1.41 | 1.67 | 1.51 | 1.80 |
| tool results per task | 194 tokens | 388 | `0.0051` | 1.23 | 1.46 | 1.34 | 1.60 |
| thin bodies | 4500 tokens | 9000 | `0.0072` | 1.23 | 1.47 | 1.35 | 1.60 |
| the wave's waits | 2 | 4 | `0.0316` | 1.28 | 1.52 | 1.39 | 1.65 |
| script output left by terse output | a tenth | a fifth | `0.0007` | 1.22 | 1.45 | 1.33 | 1.59 |
| trimmed executor prompt | 9000 bytes | 18000 | `0.0270` | 1.27 | 1.51 | 1.39 | 1.65 |
| filed returns | section 5.1's sizes | twice | `0.0114` | 1.24 | 1.48 | 1.35 | 1.61 |
| output and requests together | | | `0.2044` | 1.59 | 1.90 | 1.70 | 2.02 |
| every row at once | | | `0.3119` | 1.79 | 2.13 | 1.90 | 2.26 |

So G1 holds the ideal on the whole-A mean only while every estimate holds. Doubling the output, the
requests, the waits or the trimmed prompt each takes the mean over 1.25. Like for like G1 never
reaches it. G1 keeps the 2.0 ceiling like for like unless the output and the requests double
together, which takes `whole-C-2-r` to 2.02. These figures are the cycle alone. With the carried
review charged back, G1 starts at 1.66 to 2.12 like for like (section 5.1).

**T11's probe threshold, from the tied model.** Each extra output token a request emits adds
k × (o + w + r × (k − 1) / 2) to the cycle, because it is written back. That is 14 × 29.3e-6 =
410e-6 at rung 1 and 8 × 28.7e-6 = 230e-6 under G1, on section 5.1's rates. So:

- G1's mean leaves 1.25 on the whole-A reading at 0.0163 / 230e-6 = 71 tokens over 250, so at about
  320 tokens a request;
- rung 1's worst session leaves 2.0 on that reading at 0.0572 / 410e-6 = 140 tokens over, so at
  about 390.

The probe's stop is set at those two figures (section 7). The revision at `b72372f7` set 500, the
doubled estimate. With the writes tied, 500 a request puts rung 1's worst session at 2.08.

Both stops protect the whole-A reading, which section 0.2 says the target does not mean. Like for
like, the limits sit elsewhere:

- G1 is over the 1.25 ideal before anything grows, at a mean of 1.45, so its binding limit is the
  2.0 ceiling in `whole-C-2-r`. Output reaches it at (2 × 0.459507 − 0.7296) / 230e-6 = 824 tokens
  over 250, so at about 1070 tokens a request;
- rung 1 is over 2.0 in every session before anything grows, at 2.03 to 2.26, so like for like
  there is no output figure for a stop to sit at.

So each stop is stricter than the target on purpose. It protects the one reading on which G1 meets
the ideal and rung 1 meets the ceiling, and tripping it costs a re-derivation (section 7), never a
decision.

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
| sign-off without a fix task, with its review | `0.6367` to `0.9637`, review `0.2364` to `0.2472` | `0.2687` to `0.3002` | `0.30` |
| the run's close | `0.2005` to `0.2457` | inside sign-off's last step and the report | `0` apart |
| **phase overhead** | **`2.9071` to `3.3509`**, with fix tasks and explorers | **`0.65` to `0.70`** | **`0.75`**, 1.37 times A's mean |
| each fix task | `0.3990`, `0.5580` | `0.1192` in `whole-C-3`, `0.1045` in `whole-C-1` | under the per-task target, as a task |
| under G1, the per-task review carried to the phase | in the cycle today: reviewers `0.1895` to `0.1953`, plus their dispatches | `0.1482` to `0.2552` (C14) | none set; see below |

Planning without the explorer is derived: 0.3988, 0.6601 − 0.2493 and 0.7051 − 0.3219. Sign-off
without a fix task is section 5.1's sign-off at `S` = 4:

- `whole-C-3`: `main(4, 46022, 2999, 2648)` + 0.1715 + 0.0141 = 0.1147 + 0.1715 + 0.0141 = `0.3002`,
  where `W_s` = 3 × 250 + 80 + 2055 + 114 and `O_s` = 3 × 250 + 1898;
- `whole-C-1`, on its own readings: `0.2902`;
- `whole-C-2-r`: `0.2687`.

The phase overhead is the sum of the two, for example 0.3988 + 0.3002. A fix task is what its three
requests and its recorded executor add to sign-off: the sign-off with it less the sign-off without,
`0.4194 − 0.3002` = `0.1192` in `whole-C-3`. The revision at `b72372f7` gave sign-off `0.2498` to
`0.2720`, a phase overhead of `0.63` to `0.68` and a fix task of `0.1232`. It read a flat `P′` +
4000 a request, wrote 600 a request, and took the report at 1000 and the filing request at `0.005`.

**Rung 1's sign-off has no margin left in `whole-C-3`, where it passes its budget at `0.3002`.** The
budget stays at `0.30`, because a budget moved to fit its prediction checks nothing. What would
break it, each estimate doubled, with the planning and sign-off model of section 5.1 and no fix
task:

| Estimate | Value | Doubled | Sign-off | Phase overhead |
|---|---|---|---|---|
| as predicted | | | `0.2687` to `0.3002` | `0.6519` to `0.7009` |
| sign-off requests | 4 | 8 | `0.3363` to `0.3709` | `0.7195` to `0.7751` |
| sign-off output per request, writes tied | 250 tokens | 500 | `0.2899` to `0.3214` | `0.6731` to `0.7222` |
| the triage print | the phase reviewer's hand-back | twice | `0.2823` to `0.3173` | `0.6655` to `0.7160` |
| planning requests | 5 | 10 | unchanged | `0.6767` to `0.7298` |
| thin bodies, written in planning and read throughout | 4500 tokens | 9000 | `0.2723` to `0.3038` | `0.6937` to `0.7428` |

Only doubled sign-off requests take the phase overhead over `0.75`. `whole-C-3`'s sign-off is over
`0.30` as predicted, by `0.0002`, and each doubled sign-off row moves it further.

**Under G1 the phase overhead is `0.7984` to `0.9524`**, over its `0.75` budget on either estimate of
the carrying (C14). That is the per-task review's work arriving at the phase, not new work. Whether
the budget absorbs it, or the carried review is budgeted as a part of its own and held to its own
value test below, is the user's (section 8, decision 1). No figure is set for it here, because a
budget written to fit a prediction would check nothing.

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
| the per-task review carried to the phase, under G1 | a `diverges`, a `not-proved` on a `tdd` task, or a flagged inherited test, acted on before the merge | the phase review's filed return, per task, and the triage decision | per task, every review answered `matches`, red-first `proved` or `could-not-prove`, inherited tests `not-asked` (the review command) | runs under G1. If the after-study shows none of the three acted on, its price is the user's to weigh |

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
| T11 | the probe, then the full benchmark | — | one single-task paid probe, then three sessions | about `0.66`, then about `5.8` |
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
    explained. Its two launched that way, `RKf8vq` and `MMJ2sv`, rebuilt finals of cacheR 33634
    and 32179 in their `dispatch` lines, 65813 together. That leaves −5043 of its −70856 with no
    cause named. The fault is the final-request rebuild's, not the result reading's, and it moves
    cost between one model's stages, never out of the session.
  - What follows the cycle holds sign-off, any fix task it runs and the run's close. T1 prints them
    as three parts, bounded as section 1.5.2 bounds them. A fix task runs from an `add` after the
    cycle to that task's `done`. The close starts at the lock release, or after the landing.
  - **Added by the cost target.** `stream-cost.py` sizes each user text block of the main loop, so
    a command body a `Skill` call injects is a source of its own, `command body: <skill>`. Today
    the write is split among the request's other sources at 0.01 bytes per token (section 1.5.7).
  - **Added by the cost target.** A dispatch whose tool result is the async-launch notice keeps its
    last visible request as its final and rebuilds none. That removes the rebuild fault's phantom
    final (section 1.5.7), and the part of the `unattributed` row it explains. In `whole-C-3` and
    `whole-C-1` that is the whole row. In `whole-C-2-r` it is 65813 of 70856.
  - **Added by the fourth review.** Before a target is set for `whole-C-2-r`'s row, T1 names the
    cause of its remaining −5043. The investigation is offline: list that session's dispatches by
    how each was launched and how its last visible request ends (section 10's dispatch command), and
    set each rebuilt final's cacheR against what the stream shows of that agent. The target for
    that session follows from what it finds, and none is set before.
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
    - on `whole-C-3` and `whole-C-1`, the `unattributed` row is gone, and each model's total is
      unchanged (`4.856048` and `0.770360` for `whole-C-3`). On `whole-C-2-r` it is −5043, not
      −70856, with the same totals, until the investigation above names the rest;
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
  - `plugins/audit/scripts/manifest/audit-task.py`, for the filing verb, `done --from-return`, and
    the rule C3 puts on every form of `done`;
  - `plugins/audit/scripts/governance/commit-task-work.py`, whose `commit_message` appends a filed
    `claims` block (below);
  - `plugins/audit/agents/audit-executor.md`, `plugins/audit/agents/audit-reviewer.md`;
  - the task prose, `plugins/audit/scripts/_refs.py` and `PLUGIN-BUILD-GUIDE.md`;
  - `COMPATIBILITY.md`, whose *Not promised* list gains the wider refusal (C3);
  - the tests of each script it changes.
- **The reviewer's write.** `audit-reviewer.md` gains one *May* line: one call of the filing verb.
  Its *Must not* keeps "anything that writes", with that call as the only exception. Its paragraph
  naming who reads the answer (`:246-251` at `7b489337`) says the orchestrator carries the word into
  `done --intent`; it then names `done`, which reads the filed return (C3). The filing
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
  - `done`, in every form that passes `--commit`, under `always`, the only value of
    `review.perTask` until T6 lands (C3):
    - a plain `done --commit <sha>` with no reviewer return filed for the current start is refused,
      writing nothing, both with no `--intent` and with `--intent matches`. So is the same close
      when the only reviewer return filed is from an earlier start;
    - once the reviewer's return for the current start answers `matches`, a plain `done --commit
      <sha> --intent matches` closes, and the same close with no `--intent` records that answer.
      Over a filed `diverges`, `--intent matches` is refused, and so is `--intent not-asked` with
      its basis;
    - `done --commit <sha> --intent not-asked` with its basis closes with no return filed, and a
      `--no-change` close with `not-asked` and its basis closes as it does today;
    - `done --from-return` meets each of those the same way, and is also refused when the
      executor's return for the current start is missing. It closes when both returns are filed
      for the current start, and when the executor's is filed and the close passes
      `--intent not-asked` with its basis.

    Without the closing halves, a close that refused everything would pass. Without the plain-form
    refusals, a rule placed on `--from-return` alone would pass every case.

  Those cases hold the write to one derived path that never replaces a return already filed. They
  do not hold the task id and role to the caller's own. Those are the caller's word, so a filing
  under a role or a task not yet filed stays a followed rule. So does the reviewer running nothing
  else that writes, unenforced, as it is today (C3, *Guarantees*).
- **Added by the cost target: the phase reviewer's brief.** `/audit:phase add` saves the request's
  text verbatim beside the phase. The sign-off reviewer's computed brief carries it, every task's
  description and filed return, and one fixed question: where does a task choose something the
  request leaves open? (section 5.4). Its case: a brief computed for a phase with a saved request
  holds that text byte-identical, and one with none says so rather than leaving the field empty.
- **Added by the fourth review: what that brief carries per task under G1.** With `review.perTask:
  phase` (T6), the brief also carries, for each task closed `deferred`, its commit SHA and declared
  files, its recorded gate run, and its `tests.gate` commands resolved through
  `meta.buildCommands`. Those are the tasks with a diff, less any fix task the plan records as one
  (section 5.2). It asks the three per-task questions of each task: the intent binding against
  `git show <sha> -- <files>`, the red-first grade, and the inherited-test question bounded by that
  task's `tests.gate` (C14). Its cases:
  - a brief computed for a phase of three tasks holds each task's SHA, files and `tests.gate`
    byte-identical to the plan's;
  - a task whose `tests.gate` names a `key:project` entry the plan cannot resolve is printed with
    that entry unresolved and says so, rather than dropping it;
  - a brief for a task with no commit yet is refused, writing nothing, because the binding would
    have no diff. Without that half, a brief that carried a missing SHA as empty would pass.
- **Added by the fifth review: the claims block rides the filed return into the commit.**
  - *The gap.* This repository's `.claude/hooks/require-claim-block.py` refuses a commit on a
    claim-bearing surface, such as any `.md`, whose message has no `claims:` block. It is a
    `PreToolUse` hook on Bash (its docstring's first line, and `.claude/settings.json`), and it
    decides on a command's `git commit` statement. The plugin's commit path runs its `git commit`
    as a subprocess of its own (`run_git`, `plugins/audit/scripts/governance/_scoped_commit.py:105`
    at `7b489337`). So the Bash command the hook reads is `commit-task-work.py`'s invocation. It
    holds no `git commit` statement, and the hook lets it through with no block. The fifth review
    names two task commits of this document, `b72372f7` and `68f43cac`. Each touches a `.md` and
    carries no block (`git log -1 --format=%B <sha>`), and each carries the `Audit-Row` trailer the
    plugin's commit path writes.
  - *The fix.* The executor's filed return takes an optional `claims` text, kept verbatim.
    `commit_message` (`commit-task-work.py:494`) reads the executor's return for the task's current
    start from the filing verb's derived path. When that return carries `claims`, it is appended
    byte-identical as a paragraph of its own, after the subject and before the trailers. A return
    without it gives today's message.
  - *What the trailers need.* `with_row_trailer` (`_scoped_commit.py:670`) joins the `Audit-Row`
    trailer to the message's last paragraph, because git reads trailers from the last paragraph
    only. With no co-author line, that would be the claims paragraph. So the row trailer keeps a
    paragraph of trailers, its own when there is no co-author line.
  - *Its cases:* a filed return with `claims` gives a commit whose message holds the block
    byte-identical as its own paragraph; one without gives today's message; and with `claims` and
    no co-author line, `git log -1 --format='%(trailers:key=Audit-Row,valueonly)'` still prints the
    nonce. Each is shown red against a `commit_message` that drops the block, or that joins the
    trailer onto it.
  - *What this does not hold: presence.* A filed return with no `claims` still commits with none,
    and the hook still cannot see the commit. Requiring the block is this repository's rule, not
    the plugin's, so the plugin's verb has no ground to refuse a return for lacking it. On this
    path the block stays a followed rule, asked for by the `before-you-claim` skill when a task
    names it. A check git runs on every commit would hold it, because the commit path skips no
    hook. Such a `commit-msg` hook is this repository's configuration, not a task of this design.
- **Target** (`python3 tools/stream-cost.py <session>/stream.jsonl`, with T1's task cycle). Each
  reading is taken inside the cycle and divided by the tasks it holds, as C3's *Confirming reading*
  says:
  - no `brief for audit:audit-*` row above 200 tokens among the cycle's largest outputs;
  - the cycle's main-loop output at most 1500 tokens per task. Rung 1 predicts 1167, an estimate:
    14 requests × 250 / 3 tasks. The target before the cost target was 2350, with `feature-C-1` at
    11374 and the whole-feature sessions at 6461 to 7550 (section 1.5.4: 19382 / 3, 22650 / 3);
  - the tokens the cycle's requests put into the main loop, at most 2000 per task. Rung 1 predicts
    1555, with the writes tied to the output (section 5.1: 4664 / 3). The target was 7400 before
    the cost target, then 1500 against an untied prediction of 1000, which the tie puts above it.
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

- **Files:**
  - the config schema and `_config_rules.py` for `review.perTask` (`always` by default; `phase` for
    G1; `signals` for G2), the panel's control and the doctor's line;
  - the driver's step (T4) and the phase reviewer's brief (T3);
  - the plan schema: `deferred` as an intent answer, and the key's value recorded on the phase;
  - in `plugins/audit/scripts/manifest/audit-task.py`: `done` in every form, through
    `_locked_done`; `start`, which records the key on the phase; `add`, which gains `--fixes`; the
    filing verb's shape for a phase return (T3's verb); and the sign-off verb;
  - `plugins/audit/scripts/git/close-phase.py`, which asks sign-off's question before it merges;
  - `plugins/audit/agents/audit-reviewer.md` at `7b489337`: the *What you are handed* table
    (`:25-36`), the `mode: phase` paragraph (`:55-57`), the return format (`:220-235`) and the
    paragraph naming who reads the answer (`:246-251`). Its additions count against T8's reviewer
    ceiling;
  - `plugins/audit/scripts/_refs.py` for the key check below; its tests in
    `plugins/audit/tests/test__refs.py`, which also hold the pins over the reviewer's text; and
    `tools/prove-gates.py`, whose tables need a row for that check;
  - the tests of each script it changes.
- **Mechanism.**
  - Under `phase`, the driver dispatches no per-task reviewer. The phase reviewer's brief carries,
    for each task closed `deferred`, what T3 lists: its commit SHA and files, description, filed
    return, recorded run and `tests.gate`. It asks the three per-task questions of each task (C14).
  - *The reviewer's definition.* At `7b489337` it grades red-first `not-attempted` in `mode: phase`
    and returns one `intent` object (C14). Under `review.perTask: phase` its phase-mode paragraph
    asks the three questions of each task the brief lists, by the rules `mode: task` applies to one
    task. The phase-level `intent` keeps its meaning, an answer against `desiredOutcome`. The *What
    you are handed* table marks the per-task inputs as handed in phase mode too, one set per task.
    The return gains a top-level `tasks` array, one entry per task the brief lists:

    ```
    "tasks": [{"id": "<task id>",
               "answer": "<one word of intent.answer's list>",
               "note": "what this task's diff does, said against its description and its claim",
               "missing": ["<an input this task's entry was not handed>", ...],
               "redFirst": "<one word of intent.redFirst's list>",
               "redFirstBasis": "the command and exit code that proves it, or what was absent",
               "inheritedTests": "<one word of intent.inheritedTests's list>",
               "inheritedTestsBasis": "the gate commands read and the files they selected"}, ...]
    ```

    The entry names each word list rather than repeating it, so each list is declared once.
    For `redFirst` that is also a lint: `red_first_vocabulary_drift` requires the reviewer's return
    format to declare that list exactly once (`scripts/_refs.py:1181-1185`, through `_RF_REV_SHAPE`
    at `:1154`), so a second literal list here would turn it red. The paragraph naming who reads the
    answer gains the phase-mode reader:
    the sign-off verb, which writes each entry onto its task with that task's own commit SHA.
  - *The filing verb's phase return.* T3's verb files it under the phase id with the role
    `reviewer`. Its derived path is keyed on the head the reviewer's brief was computed at, which
    the brief records. So a review after fix tasks files beside the earlier one, and a second filing
    for one head is refused, as a second filing for one start is. It refuses, writing nothing and
    naming what is missing, a return that lacks a `tasks` entry for any task of the phase closed
    `deferred`, an entry that lacks any of the three answers or gives `not-asked` with no basis, and
    an entry naming a task outside the phase. A reviewer that follows the old definition is refused
    at filing and told which entries it owes, so it does not reach sign-off as a held phase.
  - *The key check.* The entry's keys are one tuple, read by the filing verb and by a check in
    `_refs.py` modelled on `red_first_vocabulary_drift` (`_refs.py:1189`). The check reads the
    `tasks` entry in the reviewer's return format, and fails on a key either side names that the
    other does not.
  - *The close.* Under `phase`, `done` in every form that passes `--commit` records the task's
    intent as `deferred` itself, a new answer in the plan schema, and refuses any `--intent` word,
    writing nothing. So a task the phase review must bind cannot close as `not-asked`, which
    sign-off counts as answered (`reference/execute-task.md:373-377` at `7b489337`). The exception
    is a task that a finding in its own phase's `review.findings` names as its `fixTask`: it may
    close `--intent not-asked` with its basis. `add --fixes <findingId>[,<findingId>]` writes that
    `fixTask` in the write that adds the task. It refuses a finding outside the task's phase, or
    one already naming another task, and every other verb refuses the flag through `VERB_FLAGS`
    (`audit-task.py:9834`). A `--no-change` close keeps today's rule (section 5.2).
  - *The key, once per phase.* `start` records `review.perTask`'s value on the phase when it
    promotes the phase's first task, and `done` and the driver read that value. A phase with none
    recorded reads as `always`, the default.
  - *The refusal.* The sign-off verb refuses, writing nothing, while any task closed `deferred`
    lacks any of its three answers in the phase review's filed return: an intent answer, a
    red-first grade, and an inherited-test answer, with its basis where that answer is `not-asked`.
    When the review answers for a task, sign-off writes the answer onto that task with the task's
    own commit SHA, so the answer still names the diff it judged. The question is one function in a
    helper both import, and `close-phase.py` asks it before it merges or hands over the merge
    command.
  - Under `signals`, the driver dispatches the per-task reviewer only when the task's `redFirst` did
    not come back `proved`, or when the gate row disagrees with the filed return.
- **Micro-test, offline:** a drive over the T4 fixture with each value:
  - `phase` dispatches no per-task reviewer, and every task it closes records `deferred`;
  - under `phase`, each of these on a task with a diff is refused, writing nothing:
    `done --from-return --intent not-asked` with its basis, a plain `done --commit <sha> --intent
    not-asked --intent-basis "..."`, and a plain `done --commit <sha> --intent matches`. A plain
    `done --commit <sha>` with no `--intent` closes and records `deferred`. A `--no-change` close
    with `not-asked` and its basis is accepted. Without that half, a close that refused every
    `not-asked` would pass;
  - under `always`, a plain `done --commit <sha> --intent not-asked --intent-basis "..."` closes as
    it does today, and `--intent matches` closes once the reviewer's filed return answers `matches`
    (T3's cases). Without that half, a rule that refused the plain form under every key would pass;
  - under `phase`, a task added with `--fixes` naming a finding of its own phase closes
    `--intent not-asked` with its basis, and a task not recorded that way is refused with the same
    flags. `add --fixes` naming a finding of another phase, or one already naming another task, is
    refused, writing nothing;
  - a phase whose first task started under `phase`, with the key then set to `always`: a plain
    `done --commit <sha> --intent not-asked --intent-basis "..."` is still refused;
  - a phase return that lacks one `deferred` task's entry is refused at filing, writing nothing,
    and names that task. With the entry restored it files;
  - the key check goes red when the reviewer's return format drops a key of the `tasks` entry, and
    red when the filing verb's tuple gains one the format lacks. `red_first_vocabulary_drift` stays
    green over the changed definition;
  - `close-phase.py` refuses to merge a fixture whose `deferred` task lacks one answer, and merges
    it once all three are filed;
  - a fixture whose tasks closed the G1 way, `deferred`, is refused at sign-off when one task's
    intent answer is removed from the phase review's filed return. The same holds with its red-first
    grade removed, and with its inherited-test answer removed. With all three restored it passes;
  - a fixture with no `deferred` task signs off as today, so the refusal does not fire where G1 is
    off;
  - `signals` dispatches exactly the reviewers its two conditions select;
  - `always` drives as T4 does.

  Each case is shown red first.
- **Target:** the per-task ratio of section 5.1's rung for the chosen value, like for like and
  against whole arm A. Under G1, the carried review's cost at sign-off is read beside it (section 7).
  Its confirming sessions are the after-study, run with the key set.

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
- **Expected cost.** About `0.66`, rung 1's single-task prediction with the Opus executor that
  harness's plan names (section 5.1). It is about `0.55` if G1 has been decided first. Its stop is
  `--max-budget-usd 1.5`.
- **What it confirms, each read with T1's rows:**
  - no `Read <plugin>/reference/` row;
  - the prefix the cycle's first request reads is at most 25000 tokens (T2);
  - the cycle's main-loop requests are at most 4 (T4);
  - the cycle's main-loop output per request is at most 320 tokens under G1, or 390 without it.
    These are the points at which section 5.3's tied model puts G1's mean over 1.25, and rung 1's
    worst session over 2.0, on the whole-A reading. Each is stricter than the target on purpose.
    Like for like, G1's binding limit is the 2.0 ceiling, which output reaches at about 1070 tokens
    a request, and rung 1 is over the ceiling before its output grows (section 5.3);
  - the cycle's writes per task follow its output as section 5.1 ties them, with that rung's tool
    results: at most the output plus 200 tokens a task under G1, against the 194 assumed, or plus
    400 without it, against the 388 assumed. Each bound is its rung's assumption rounded up. Read
    against 388, G1 would pass at twice its own assumption;
  - no brief above 200 tokens among the largest outputs (T3);
  - the executor's first start written is at most 16000 tokens (T8);
  - the session is at most `0.75`.
- **What it does not confirm.** The per-task target. Its single task runs its executor on the plain
  session's own model. There rung 1 is predicted at 2.22 times plain, and G1 at 1.85, or 2.25 with
  the review it defers charged back (section 5.1). Under G1 the probe runs no phase review, so the
  carried review is read only in step 3. So is the phase reviewer's `tasks` array: step 3 is the
  first time a live reviewer is asked the three questions per task. What stands before it is
  offline: the filing verb's refusal of a return missing a task's entry, and the check that the
  reviewer's return format and the verb's shape name the same keys (T6). A probe reading over a
  ceiling stops step 3 until the estimate behind it is re-derived and the prediction re-computed.

**Step 3, the full benchmark.** It runs only once the probe has passed.

- **Setup.** A copy of `<h2>` that changes `benchlib.EXPERIMENTS` and `pins.json` → `pluginSha`, and
  nothing else. That follows the harness's own precedent: v2 is "a copy of `../bench-feature/`
  extended, not an edit of it". A suggested name is `fixtures/bench-feature-cost`, and its records go
  to its own experiments folder. It runs arm C only: at least three sessions, as the protocol fixes
  per arm (`benchmark-feature-design.md`, section 6), in a seeded order, at the commit that lands the
  tasks. One study is enough for every target, because each target reads its own row of
  `stream-cost.py`.
- **Expected cost.** About `5.8` for the three: rung 1's predicted sessions, 1.7950 + 1.9874 + 2.0105.
  It is about `5.6` under G1, on C14's upper estimate of the carried review: 1.7306 + 1.9147 +
  1.9464. Re-run `python3 <h2>/estimate.py` before agreeing a budget, since it does not model this
  design. The revision at `b72372f7` gave `5.6` and `4.8`.

**This study's protocol is the whole-feature benchmark's, and it lands with that benchmark's phase,
not with this one** (section 0). Until that phase merges, the sections cited here are read at
`a289dcbb`.

| Target | Row read per session | Predicted |
|---|---|---|
| **the per-task ratio** | the cycle's billed cost (T1's cycle, main loop + its agents) ÷ `0.459507`, arm A less its first and last main-loop requests (the open-and-close command), which is the reading the target is taken to mean (section 0.2). ÷ `0.547004` is printed beside it | the ceiling is at most 2.0 in every session. Rung 1 predicts 2.03 to 2.26, over it in every session, and 1.70 to 1.90 against whole arm A. G1 predicts 1.33 to 1.59, under it in every session, and over the ideal of 1.25 in every session. Against whole arm A G1 is 1.12 to 1.33 |
| **the whole-feature ratio** | `all models priced` ÷ `0.547004` and ÷ `0.843470` | rung 1 3.28 to 3.68, and 2.13 to 2.38; G1 3.16 to 3.56, and 2.05 to 2.31 |
| **the phase overhead** | planning + sign-off + the close, less the project's own agents and fix tasks | at most `0.75`. Rung 1 predicts `0.65` to `0.70`, and G1 `0.80` to `0.95` with the carried review (section 5.4) |
| under G1, the carried review | the sign-off reviewer's dispatch, billed (the billed-span command over its request), less the recorded phase review's `0.1522` to `0.1715` | `0.1482` to `0.2552` (C14) |
| T2 | the prefix the cycle's first request read, by origin; `Read <plugin>/reference/…` rows | no reference rows; prefix at most 50000 |
| T3 | inside the cycle, per task: briefs among its largest outputs, its main-loop output, its writes | none above 200; at most 1500 and 2000 |
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

1. **Where the per-task review runs, and what it returns (C5, C14).** The user chose G1 on this
   decision's earlier wording. That wording named one thing moving, "the per-task intent check". It
   is restated here with the full list, for the user to confirm.

   **What the per-task review returns today**, before each task commits (C14):
   - the intent binding: does the diff do what the description asked, and does the claim describe
     the diff;
   - the red-first grade, with a `not-proved` on a `tdd` task sent to a human;
   - the inherited-test question, bounded by the task's `tests.gate`.

   **Which plain figure the target means is part of this decision.** Section 0.2 prints the per-task
   ratio against arm A less its open and close, and against whole arm A. It takes the first, like for
   like, as the target's meaning. Like for like, rung 1 is 2.03 to 2.26 times plain and misses the
   ceiling in every session. Against whole arm A it is 1.70 to 1.90. On `feature-C-1`'s single task,
   a whole session against whole plain sessions, it is 2.22 (section 5.1).
   - (a) Keep the review on every task. This is rung 1 as predicted, with all three answers before
     the commit.
   - (b) G2: add `review.perTask: signals` with a default of `always` (minor). The review then runs
     only on R8's two computed conditions: a `redFirst` that did not come back `proved`, and a gate
     row that disagrees with the filed return. It never runs on the self-declared `task.risk` (C5,
     *Guarantees*). A task it does not review gets none of the three answers, and nothing carries
     them. Predicted at 1.55 to 1.80 like for like, and 1.30 to 1.51 against whole arm A.
   - (c) G1: add `review.perTask: phase` with a default of `always` (minor). No reviewer runs per
     task. Each of the three answers is carried into the phase reviewer's computed brief, per task,
     with the task's commit SHA, files, filed return, recorded run and `tests.gate`. Each such task
     closes `deferred`, not `not-asked`, whichever form of `done` closes it. Sign-off, and the
     plugin's merge after it, refuse while any `deferred` task lacks any of its three answers
     (section 5.2, T3, T6). What is given up is the timing: each answer arrives before the merge,
     not before the commit.
     - Predicted on the cycle: 1.33 to 1.59 like for like, a mean of 1.45, and 1.12 to 1.33 against
       whole arm A, a mean of 1.22.
     - Carrying costs `0.1482` to `0.2552` a session at sign-off. Charged back to the cycle, that is
       1.66 to 2.12 like for like. The phase overhead is then predicted at `0.80` to `0.95` against
       its `0.75` budget (section 5.4).
     - On `feature-C-1`'s single task it is 1.85, or 2.25 with the deferred review charged back.
   - (d) Either of the above as the default: a major release (section 2).

   **Against the target, plainly.** The 2.0 ceiling like for like: rung 1 misses it in every
   session, and G1 and G2 meet it in every session, on the cycle as section 0.2 defines it. With its
   carried review charged back, G1 reaches 2.12 in `whole-C-2-r` on the upper estimate. The 1.25
   ideal: no option reaches it like for like. G1 reaches it only against whole arm A, on the mean,
   with a margin of `0.0163` that doubling any one of four estimates removes (section 5.3).

   **Recommendation: (c), G1, carrying all three answers.** It keeps every answer the per-task
   review gives, each still bound to its task's own commit, and moves only their timing. It moves
   them to where the findings were acted on in every recorded case (section 1.6). (b) gives answers
   up instead of moving them, on a trigger that measures the red-first helper's limit.

   The facts about (c) that are not reasons for it:
   - it saves `0.0641` to `0.1739` a session against (a), where (b) saves `0.2117` to `0.2212`. The
     review's work moves to the phase rather than leaving;
   - it takes the phase overhead over its budget. So choosing (c) also means deciding whether the
     `0.75` budget absorbs the carried review or the review gets a budget line of its own
     (section 5.4).

   The consequence to publish: a misread task, a `not-proved` red-first or a vacuous inherited test
   is found before the merge, not before its commit, and is repaired by a fix task. Keeping (a) is
   coherent if the per-commit timing is wanted for itself. Then the ceiling is missed like for like
   in every session.
2. **The light path (C1).**
   - (a) Do not build it.
   - (b) Build it behind a key that defaults off. The README's enforced row then has to say it does not
     cover light-path work.
   - (c) Build it on by default (major).

   **Recommendation: (a).** C1 in section 3 predicts that its inline part costs more than it saves
   once C3 lands, and it is the one option that gives up an enforced row. Re-priced at rung 1's prefix
   with a hook holding the tool rule (C15), it still costs about `0.044` more a session.
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
   - one single-task probe, about `0.66` (about `0.55` under G1), stopped at `1.5`;
   - the full benchmark's three arm C sessions, about `5.8` (about `5.6` under G1).

   **Recommendation:** agree both budgets now, so that step 3 is not waiting on a decision once
   step 2 passes.
5. **Main-loop TTL (C6a).** Whether the plugin can set it is **unknown**. The host facts name the
   settings and environment variables a user sets, and nothing says a plugin can ship one (section 9).
   Which TTL a user's main loop gets also follows their billing (section 1.4).
   - **Measured.** The longest gap between main-loop requests was 67 to 81 seconds in the three arm C
     sessions (the gap command). The one-hour write bought nothing there.
   - **Priced.** At five minutes, today's main-loop writes would have cost three eighths less:
     211809, 194155 and 216860 tokens × 3.0e-6 = `0.6354`, `0.5825` and `0.6506` (`cacheW1h` of the
     `plan`, `gate` and `close` rows). Under rung 1 the main loop writes 33117 to 42331 tokens in a
     session, an estimate: `P′` less what was cached, plus the cycle's writes and sign-off's, each
     tied to its output as section 5.1 ties them. So the difference falls to `0.099` to `0.127`.
     The revision at `b72372f7` gave 31265 to 41114 tokens and `0.094` to `0.123`.

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
| a session's first and last main-loop request, and the session less both: arm A's open and close, and arm C's final report (sections 0.2, 5.1) | the open-and-close command below, from a checkout of the result-reading commit |
| how much of the main loop's output came back as its own cache writes (section 5.1) | the write-back command below, from the same checkout |
| each dispatch's brief and hand-back bytes, the review's three answers, and its work beyond its start, billed and at Opus rates (C14, section 5.1) | the review command below, with the first and last main-loop request, from the same checkout |
| rung 1, G2 and G1, and every doubled row (sections 5.1, 5.3, 5.4) | the arithmetic written in section 5.1, on the span, open-and-close, write-back and review commands' readings and `contexts:` → `$/request` |

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

The findings command reads an arm C fixture's final plan, read-only. It prints each task's test
mode, its `tests.gate` and its intent answer, then each phase finding with its severity, its fix
task and the start of its resolution. The `tests.gate` column was added by the fourth review. Every
task of the three arm C plans printed `['test']` there.

```
git -C <fixture> show main:docs/audit/audit-plan.json | python3 -c "import json,sys; m=json.load(sys.stdin); [print(t['id'], t['tests']['mode'], t['tests'].get('gate'), (t.get('intentCheck') or {}).get('answer')) for p in m['phases'] for t in p['tasks']]; [print(f['id'], f['severity'], f.get('fixTask'), f['resolution'][:50]) for p in m['phases'] for f in (p.get('review') or {}).get('findings') or []]"
```

The open-and-close command takes a stream. It prints the session's total, the cost of its first
and last main-loop requests with the last one's output, their share, and the session less both.

```
python3 - <x2>/<session>/stream.jsonl <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); c = r["costs"]
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
total = sum(c[q["id"]]["total"] for q in r["requests"])
a, z = c[main[0]["id"]]["total"], c[main[-1]["id"]]["total"]
print("total %.6f; first %.6f, last %.6f (output %.0f); both %.1f%%, the session less both %.6f" % (
    total, a, z, (r["output"] or {}).get(main[-1]["id"], 0.0), 100 * (a + z) / total, total - a - z))
EOF
```

On `whole-A-1`, `whole-A-2` and `whole-A-3` it printed first and last `0.041093` and `0.038185`,
`0.048586` and `0.046934`, `0.040731` and `0.046963`. The shares were 15.7, 15.9 and 16.4 percent,
and the sessions less both `0.426059`, `0.505162` and `0.447301`. On `whole-C-3`, `whole-C-1` and
`whole-C-2-r` the last request's output was 1898, 1729 and 1722, and on `feature-C-1` 1239.

The write-back command takes a stream and, optionally, a first and last main-loop request. It sums
the requests' measured output, and the main loop's own output the tool books as written into the
cache at the request after each one.

```
python3 - <x2>/<session>/stream.jsonl [<first> <last>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1]))
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
lo, hi = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1, len(main))
made = dict((main[i]["id"], i) for i in range(1, len(main)))
out = sum((r["output"] or {}).get(q["id"], 0.0) for q in main[lo - 1:hi])
back = sum(it["tokens"] for it in r["content"]["items"] if not it.get("base") and it["source"].startswith("output:")
           and lo <= made.get(it["request"], 0) <= hi)
print("requests %d-%d: output %.0f, written back as the loop's own output %.0f, %.2f" % (lo, hi, out, back, back / out))
EOF
```

On the three arm A sessions, whole, it printed 0.82, 0.79 and 0.86. On the arm C cycles, `15 36`,
`12 34` and `15 42`, it printed 0.97, 1.02 and 1.32. On `whole-C-3`'s `22 23` it printed 183 and
4251.

The review command takes a stream and a first and last main-loop request. For each dispatch those
requests made, it prints the brief's and the hand-back's bytes, and the intent, red-first and
inherited-test words the hand-back carries. It also prints the dispatch's billed cost, its reads,
writes and output beyond its first request's start, and those re-priced at Opus's rates.

```
python3 - <x2>/<session>/stream.jsonl <first> <last> <<'EOF'
import importlib.util as u, json, re, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
r = sc.analyse(sc.load_events(sys.argv[1])); lo, hi = int(sys.argv[2]), int(sys.argv[3])
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
pos = dict((q["id"], i + 1) for i, q in enumerate(main))
brief, back = {}, {}
for l in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(l) if l.strip() else {}
    m = e.get("message") if isinstance(e.get("message"), dict) else {}
    for c in m.get("content") if isinstance(m.get("content"), list) else []:
        if c.get("name") in ("Agent", "Task"):
            brief[c["id"]] = len(((c.get("input") or {}).get("prompt") or "").encode())
        if c.get("type") == "tool_result" and c.get("tool_use_id") in brief:
            x = c.get("content")
            back[c["tool_use_id"]] = x if isinstance(x, str) else "".join(t.get("text") or "" for t in x)
for t, a in r["session"]["agents"].items():
    qs = [q for q in r["requests"] if q["context"] == t]
    if a["context"] != sc.MAIN or not qs or not lo <= pos.get(a["request"], 0) <= hi: continue
    f = [q for q in qs if not q["reconstructed"]][0]
    cr = sum(q["cr"] for q in qs) - f["cr"]; cw = sum(q["cw5"] + q["cw1"] for q in qs) - f["cw5"] - f["cw1"]
    out = sum((r["output"] or {}).get(q["id"], 0.0) for q in qs); h = back.get(t, "")
    words = [re.findall(r'"%s"\s*:\s*"([a-z-]+)"' % k, h)[:1] for k in ("answer", "redFirst", "inheritedTests")]
    print("%d %s: brief %dB, hand-back %dB %s; billed %.4f; beyond its start read %d, written %d, output %.0f, %.4f at opus rates" % (
        pos[a["request"]], a["type"], brief.get(t, 0), len(h.encode()), words, sum(r["costs"][q["id"]]["total"] for q in qs),
        cr, cw, out, cr * 0.2e-6 + cw * 5.0e-6 + out * 20e-6))
EOF
```

Run over each arm C session from its cycle's first request to its last request (`15 61`, `12 52`,
`15 55`), it printed the following:

- the per-task reviewers' briefs, 2373 to 4597 bytes;
- their hand-backs, which sum to 10322, 9655 and 10251 bytes;
- their words, `matches` in each, red-first `proved` six times and `could-not-prove` three times,
  and inherited tests `not-asked` in each;
- their work beyond the start at Opus rates, which sums to `0.2042`, `0.2048` and `0.1996` before
  rounding, from 5484, 5501 and 5432 output tokens;
- the first executors' hand-backs, 4054, 3954 and 3979 bytes;
- the phase reviewers' hand-backs, 5404, 4610 and 4325 bytes.

The background executors' hand-backs print 1188 bytes, the launch notice. On `feature-C-1` with
`6 13` it printed the reviewer's brief at 4742 bytes, its hand-back at 3550, its work at `0.0996`,
and the executor's hand-back at 6142.
