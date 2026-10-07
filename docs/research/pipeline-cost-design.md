# Pipeline cost design — cutting the fixed part without spending a guarantee

[pipeline-cost-analysis.md](pipeline-cost-analysis.md) measured what a pipeline run pays for. This
document decides what to change. It compares each candidate change on the same criteria, recommends
one structure, and breaks it into implementation tasks. Each task has a target a tool can re-derive,
and each names the benchmark session that will confirm or refute it.

It builds on two earlier documents and does not repeat them. The analysis supplies the stage and
class costs. [token-efficiency-audit.md](token-efficiency-audit.md) supplies an earlier backlog of
recommendations, which section 0.1 checks against the tree. No model call was made to write this
document.

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
the plugin the whole-feature study runs. The `stream-cost.py` figures are the tool's output at the
commit that last changed this document (`git log -1 --format=%h -- docs/research/pipeline-cost-design.md`).
Re-derive them from a checkout of that commit. Prices are the plugin's shipped table,
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
- writes out the early reads the run line had left implicit.

`stream-cost.py` now classes the bytes an `Edit` emits by the path it writes, which moved the main
loop's edit of the plan from the file class to the task class. Every figure below is re-derived on
that basis.

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
| ...of which the task's own requests wrote | 21857 | `--json` → `items` of the main context, summed by the request that wrote them (section 1.2) |
| price of one more request, main loop / executor / reviewer | `0.0210` / `0.0063` / `0.0050` | `contexts:` → `$/request` |
| main-loop requests | orient 2, plan 5, gate 3, close 5 | `per stage, as billed` → `req` |
| agent starts | executor 16952 tokens, five-minute write on opus (`0.0848`); reviewer 15878, on the sonnet row (`0.0397`) | `largest cache writes`, `agent start` rows |
| briefs typed by the main loop | 2840 and 2817 output tokens (`0.0568`, `0.0563`) | `largest outputs` |
| main-loop output | 14031 tokens | `output pool, measured: main loop` |

**Which main-loop requests are per task (inference).** The main loop's tool calls and text were
listed from the stream:

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

After the request that wrote the prose, the run-level requests are the manifest read, the lock, the
lock release and the report. The rest are per task: six steps, and two requests that happened
because something went wrong. The six steps:

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
  The tool classes their work as task work, by its rule, but a run pays it once:
  `L(m) = U + (H × m − G) × r`, where:
  - `U` = `0.0711`: their output, 2111 tokens × o = 0.0422 (`--json` → `requests`, the `out` of those
    five); their input, 0.00004; and the content they added to the cache, 3598 tokens × w = 0.0288
    (692 + 1847 + 653 + 406, from `items`, grouped by the request that wrote each);
  - `H` = 3192, the part of that content every per-task request reads (692 + 1847 + 653);
  - `G` = 6345, the reads that content misses because it enters the cache one, two and three
    requests into the `m` (692 × 1 + 1847 × 2 + 653 × 3).

  At m = 12: 0.0711 + (3192 × 12 − 6345) × 0.2 / 10^6 = `0.0774`.
- **Task work paid per task.** `t × N + c × r × k × N(N−1)/2`, where:
  - `t` = `0.7049` at k = 8: the task class less L(12), that is 0.7823 − 0.0774;
  - `c` = 21857 at k = 8: the content a task's own requests leave in the main loop
    (2616 + 5159 + 1458 + 1229 + 3646 + 1195 + 2985 + 3569);
  - the square term holds the reads of `c` by every request of every later task.

  The release and the report read every task's content once, and `t` already holds that read, so it
  has no term of its own. The first draft added `2 × (N−1)` such reads and so counted them twice.

  For k = 6, both come from `feature-C-1` less its two one-off requests. `c` = 21857 − 1229 − 3569
  = 17059. `t` = 0.7049 − 0.0925 = `0.6124`, where 0.0925 is what those two requests cost:
  - their output, (630 + 1769) × o = 0.0480;
  - their input, 0.00002;
  - the content they added, (1229 + 3569) × w = 0.0384;
  - that content's reads by the requests that remain, (1229 × 4 + 3569 × 1) × r = 0.0017;
  - their own reads of earlier per-task content, (7775 + 14074) × r = 0.0044. Each figure is the
    request's `cr` less the 79461 run tokens and the 3192 above; the second also less the first's
    1229.
- **File class.** `0.2129 × N`. This assumes every task is the size of `feature-C-1`'s task.

**Prediction, today's pipeline:**

| | k | m | run | task, once per run | task, per task | file | total |
|---|---|---|---|---|---|---|---|
| N = 1 | 8 | 12 | `0.7532` | `0.0774` | `0.7049` | `0.2129` | `1.7484` (measured: `1.748411`) |
| N = 1 | 6 | 10 | `0.7214` | `0.0762` | `0.6124` | `0.2129` | `1.6229` |
| N = 5 | 8 | 44 | `1.2617` | `0.0979` | `3.8742` | `1.0645` | `6.2983` |
| N = 5 | 6 | 34 | `1.1028` | `0.0915` | `3.2669` | `1.0645` | `5.5257` |

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

No recorded session reached these, so each is an assumption or an open question for the benchmark in
section 7:

- **sign-off.** `/audit:phase` ends with it, and both recorded plugin sessions were `/audit:run`
  (`cat <x>/feature-C-1/prompt.txt <p>/prompt.txt`). Where a figure needs sign-off, `S` = 6 main-loop
  requests is assumed. `phase-signoff.md` numbers five steps, and the first of them spawns a reviewer.
  That is an assumption, and T5 replaces it with a reading.
- **planning verbs.** The whole-feature benchmark's arm C plans with `/audit:phase add` and
  `/audit:task add`. How many times a session invokes each, and whether every invocation injects the
  command body again, is unmeasured.
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
- **which requests are per run.** Read off one session's tool calls (section 1.1). A run that, say,
  re-reads the manifest per task moves work from `L` to `t`.

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

C1 to C6 are the candidates the task named. C7 and C8 are what the evidence pointed to.

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

The per-task reviewer is skipped too, which adds C5's `0.2024`. At N = 1 that gives `0.2781` with an
opus executor and `0.0963` with a sonnet executor. The sum leaves out one interaction, worth
14561 × 0.2 = `0.0029`: the skipped dispatch would have read the inline work, not the brief and
hand-back.

At N = 5 the square term changes too:

- Each task's main loop now makes 15 requests: eight, less the dispatch and the reviewer dispatch,
  plus nine inline.
- Each task leaves 27613 tokens in it: 21857 + 14561 − 2395 − 2764 − 3646. What leaves is the
  executor's brief and hand-back rows, and the reviewer's two together (2180 + 1466).
- That is 27613 × 0.2e-6 × 15 × 10 = `0.8284` against today's `0.3497`, a cost of `0.4787`.

So N = 5 gives 5 × 0.2781 − 0.4787 = `0.9118` with an opus executor and 5 × 0.0963 − 0.4787 =
`0.0028` with a sonnet one, both at k = 8.

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
with the key on, read for main-loop requests and executor contexts.

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

For the phase run form, see section 5.

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
`largest cache writes`, summed, and the run class `$write`.

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
a PreToolUse check on the `Agent` call could, and is not proposed here. A missing filing is caught at
the close, because `done --from-return` refuses when no return is filed.

**The reviewer's one write, and what holds it.**

- *What changes.* The reviewer's prompt gains one line under *May*: one call of the filing verb.
  Its *Must not* keeps "anything that writes", with that call as the only exception.
- *What holds the write to one path.* The verb itself. It takes the task id and the role, and no path
  argument. It derives the one file it writes, the role's return for that task in the evidence
  directory, and refuses a return whose shape is incomplete without writing anything. So the only file
  this write can produce is the reviewer's own return. T3 adds the cases that pin it: a path-like
  argument refused, a malformed return writing nothing, and the written path equal to the derived one.
- *What does not hold it.* `verify-invariants.py`'s `commit-scope` grades the close commit against
  the evidence directory as a whole (`commit-task-work.py` stages that directory), so it cannot tell
  the reviewer's return from any other file there.
- *What nothing checks.* That the reviewer runs nothing else that writes stays a followed rule, as it
  is today: its Bash can write and nothing refuses it, which its own prompt says ("Nothing refuses
  these"). The filing verb widens what the reviewer is *told* it may do by one call. It does not widen
  what the harness lets it do.
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

**Confirming reading.**

- `largest outputs` holds no `brief for audit:audit-*` row above 200 tokens.
- `output pool, measured: main loop` is at most 5000 tokens per task. With C7's composite verbs, as the
  after-study will have them, the prediction for one task is 4472. That is derived:
  14031 − (2840 + 2817 − 120) − (1723 + 1769 − 100) − 630, the last term being the re-check's output.
  With C3 alone it is 5102, which is above the target.
- `contexts:` → `main`, `task` divided by the task count is at most 11000. For one task with C7, the
  prediction is 9547: the 3598 tokens of the run's own requests plus the 5949 a task leaves (section 5).

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
- the brief carried by the main loop, `0.0191`;
- its hand-back carried, `0.0129`;
- the dispatch request's read of the prefix, 91886 × 0.2 = `0.0184`.

That is `0.2024`. With every task skipped at N = 5 and k = 8, the square term shrinks two ways.
Each task leaves 3646 fewer tokens (21857 → 18211), and each later task makes one request fewer
(8 → 7). The prediction is 5 × 0.2024 + (8 × 21857 − 7 × 18211) × 0.2e-6 × 10 = `1.1068`. The
first draft counted only the first of the two, as `1.0704`.

After C3 and C7 the brief and the hand-back are already gone. The marginal saving then falls to the
stage plus one request at the smaller prefix: 0.0957 + 47003 × 0.2e-6 = `0.1051` per task. 47003 is
what that request would read in section 5's model: 41055 run tokens, the 3192 of the run's own
requests, and 2756 of the task's own written before it (2616 + 140).

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

**Confirming reading.** The reviewer contexts per session in `contexts:`. For quality, R8's section 7.5
count: tasks where `always` returned `diverges` or `cannot-tell` that the gate would have skipped.

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
  close attempts. The saving is `0.0802` per task, from three parts:
  - their reads, (90428 + 96761 + 97956) × 0.2 / 10^6 = `0.0570`. Of that, 0.0477 is run tokens
    (3 × 79461), 0.0019 is the run's own requests' content (3 × 3192), and 0.0074 is per-task
    content;
  - the re-check's output, 630 × 20 / 10^6 = `0.0126`;
  - the re-check's content, written by the next request and read by the three that remain:
    0.00983 + 1229 × 3 × 0.2 / 10^6 = `0.0106`.

  The outcome the close composes, and the retry's output and content, are counted in C3, not here.
  At N = 5 each task also leaves 1229 fewer tokens and makes 5 requests instead of 8:
  5 × 0.0802 + (8 × 21857 − 5 × 20628) × 0.2e-6 × 10 = `0.5444`.
- **At k = 6** only the close folds into the commit, so one request goes. Its read is
  (96761 − 1229) × 0.2 / 10^6 = `0.0191` per task. At N = 5:
  5 × 0.0191 + 17059 × 0.2e-6 × (6 − 5) × 10 = `0.1296`.

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

**Confirming reading.** `per stage, as billed` → `req`: plan, gate and close requests per task, at
most 5.

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

### Considered and set aside

- **A fresh main loop per task.** This trades the square term for paying, per task, what a run pays
  once. After the recommended change, that is `0.3263` (derived):
  - the run write once the prose is cut, `0.2333`;
  - its output, `0.0109`;
  - the early reads, `0.0110`;
  - the run's own requests' work, `0.0711`.

  The square term is 5949 × 0.2e-6 × 5 × N(N−1)/2 (section 5), so break-even is at about 110
  tasks: 2 × 0.3263 / (5949 × 0.2e-6 × 5). Below that, one main loop is cheaper. The first draft
  counted the run write alone, against a larger per-task content, and put break-even near 45.
- **A cheaper model for the main loop**, through a command's `model:` frontmatter. The main loop holds
  every followed rule. And per the host facts, a model switch mid-session re-reads the whole history
  with no cache hit. The model is the user's choice, not a cost lever this design takes.
- **`omitClaudeMd`.** This is R5, unchanged. The executor needs the project's `CLAUDE.md`, as R5
  already said.

## 4. Side by side

All savings are predictions in USD, from section 1's model, at k = 8, the per-task shape
`feature-C-1` recorded. A figure in brackets is the same prediction at k = 6, where the candidate's
own section gives one. "Rows" means rows of the README's enforced and followed tables.

| | N = 1 | N = 5 | Guarantees | Maintenance | COMPATIBILITY.md | Verdict |
|---|---|---|---|---|---|---|
| C1 light path, executor on opus / on sonnet | `0.2781` / `0.0963` | `0.9118` / `0.0028` | an enforced row stops covering the work; isolation lost | a second execution path | key additive; default on is major | not recommended |
| C2 by verb, state and moment | `0.2914` (`0.2802`) | `0.4708` (`0.4147`) | none, if every followed row stays reachable | more files; lints re-pointed | none | **recommended** |
| C3 computed brief, filed return | `0.2905` | `1.6874` | no row of either table; a return's shape and stamp become checked; the reviewer gains one write, held to its own return by the filing verb | prose becomes a tested script | additive | **recommended** |
| C4 enforced restatements out | `0.0913` (`0.0878`) | `0.1475` (`0.1299`) | none, by construction | lower | none | **recommended**, inside C2 |
| C5 reviewer by risk | `0.2024` per skipped task | `1.1068` if every task skips | one followed check narrowed | a config key | key additive; gated default is major | the user's (section 8) |
| C6a main-loop TTL | `0.2791` (`0.2647`) | `0.5414` (`0.4694`) | none | none | none | the user's setting; measure gaps first |
| C6b fork reviewer | `−0.0829` per task | | an enforced row lost | | | rejected |
| C6c shared agent starts | `0` | up to `0.3911` | none | none | none | measure; nothing to build |
| C7 five requests per task | `0.0802` (`0.0191`) | `0.5444` (`0.1296`) | none | composite verbs | additive | **recommended** |
| C8 verb-scoped command reads | `0` | per invocation, section 3 | none | dispatcher plus verb files | none | **recommended** |

The rows do not add up. C3 shrinks what C7's removed requests would have read, and C2 shrinks the
prefix every request reads. Section 5 computes the recommended set once, together.

## 5. Recommendation

**The main loop keeps the decisions. Scripts compute everything else and hand it over by reference.
Prose arrives by verb, by state and at the moment it applies.** That is C3 and C7, with C2 and C8, and
C4 as the rule for what a cut may delete.

It is the structurally correct option for two reasons, and cost is not one of them:

- **It moves rules toward mechanisms.** Where the task prose admits that nothing checks a return's
  shape, its stamp or a retry's context, the first two become the filing verb's exit code and the
  third is computed by the brief script. No enforced row is touched.
- **It takes the existing direction of travel.** Every verb that replaced a prose procedure has moved
  work off the model. The earlier audit said this direction "should continue", in section 4.6.

C1 is the opposite direction: work moved into the dearest context, with an enforced row given up.

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

  Against k = 6, the same after state is 0.6124 − 0.3872 = `0.2252` lower per task.
- **The square term** at N = 5 becomes 5949 × 0.2e-6 × 5 × 10 = `0.0595`.

| | run | task, once per run | task, per task | file | after | today, k = 8 | saving | today, k = 6 | saving |
|---|---|---|---|---|---|---|---|---|---|
| N = 1 | `0.3291` | `0.0755` | `0.3872` | `0.2129` | `1.0047` | `1.7484` | `0.7437`, 42.5% | `1.6229` | `0.6181`, 38.1% |
| N = 5 | `0.4933` | `0.0883` | `1.9955` | `1.0645` | `3.6416` | `6.2983` | `2.6566`, 42.2% | `5.5257` | `1.8841`, 34.1% |

The two one-off requests account for the difference between the two savings: `0.1256` at N = 1 and
`0.7725` at N = 5 (derived: 0.7437 − 0.6181 and 2.6566 − 1.8841). If neither recurs, that part is
not there to save.

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

**Facts about the recommended set, not reasons for it.**

- **Effort.** About 104 kilobytes leave the read-first path of `/audit:run`, derived: 153701 − 50000.
  The change adds one extended script, a filing verb, composite verbs, `done --from-return`, a
  dispatcher for two commands, and one new lint.
- **Blast radius.** Every command that names a reference file; the tests and drift lints that name the
  reference files (section 3, C2, has the commands that count them); both agent prompts; the plugin
  README's followed table; `PLUGIN-BUILD-GUIDE.md`.
- **Risk.** A followed rule may become unreachable at the moment it applies. The selector and the
  anchor lint in T2 hold against that.

**What it does not do.** It takes nothing from the enforced table, and it does not narrow the per-task
review. C5 stays the user's decision. It does loosen one rule that is in the reviewer's prompt and
not in either table: the reviewer gains one write, held to its own return by the filing verb (C3,
*Guarantees*).

## 6. Implementation tasks

Every target is re-derived by `tools/measure-context.py` or `tools/stream-cost.py` at the landing
commit, with `--bytes-per-token 2.63` where it applies.

### T1 — The instruments read what this design predicts

- **Files:** `tools/measure-context.py`, `tools/stream-cost.py`.
- **What:**
  - `measure-context.py` gains `--sections`: bytes per heading, and per declared line range for a
    file with one heading, under the classification table this document uses. It also gains entries
    for `/audit:phase add`, `/audit:task add`, and the phase run form before and at sign-off.
  - `stream-cost.py` gains, per context, the longest gap between consecutive requests and every
    dispatch's `start_cR` by agent type. It also counts plugin command-body injections and reference
    re-reads per session.
- **Target:**
  - `measure-context.py --ref 7b489337c06d --sections` prints this document's class sums for the three
    `/audit:run` files (keep 77811, conditional 27767, elsewhere 25037, maintainer 23089).
  - `stream-cost.py <x>/feature-C-1/stream.jsonl` prints `start_cR` 0 for both agents and a longest
    main-loop gap.
  - Each new selftest case is shown red before it is trusted.
- **Confirming session:** none, because this is offline.

### T2 — Verb-, state- and moment-scoped reading, with enforced restatements moved out (C2, C4, C8)

- **Files:**
  - `plugins/audit/reference/*.md`, cut into a core and condition files;
  - every `plugins/audit/commands/*.md` that names a reference file;
  - `plugins/audit/scripts/manifest/audit-task.py`, whose `start` prints which condition files apply;
  - `plugins/audit/scripts/_refs.py`, and the tests that name reference files;
  - `plugins/audit/README.md`, the followed table's "Stated in";
  - `PLUGIN-BUILD-GUIDE.md`, `CHANGELOG.md`;
  - `tools/measure-context.py`, `tools/verify.sh`, `.github/workflows/ci.yml` and
    `tools/gate-parity.py`, for the ceiling gate below.
- **Target** (`python3 tools/measure-context.py --ref <commit> --bytes-per-token 2.63`). Every row
  is one quantity: an entry's `total` line, its command body without the frontmatter plus the files
  it reads first.

  | Entry | Total, at most | At `7b489337` |
  |---|---|---|
  | `/audit:run` | 86000 bytes: C2's 80000 read first, plus the 5773-byte body C2 does not cut | 159474 |
  | `/audit:phase add` | 30000 | 242068 |
  | `/audit:task add` | 45000 | 108170 (C8; section 10 has the command until T1 adds the entry) |
  | `/audit:phase` run form, before sign-off | 95000 | 242068 |

  A new lint checks that every followed row's "Stated in" resolves to a heading in a file some
  command reads, and it is shown red before it is trusted. A ceiling gate, `measure-context.py
  --gate`, holds those maxima in CI. It reads the same `total` line per entry and nothing else, so
  the gate and this table cannot measure two different things. The prose grew between `v3.1.0` and
  `a73b836a` (the analysis, section 6), so without a gate the cut would rot.
- **Confirming session:** the after-study in section 7. It reads the `Read <plugin>/reference/…` tokens
  per session and the run class `$write`.

### T3 — Computed briefs and filed returns (C3)

- **Files:**
  - `plugins/audit/scripts/status/audit-lookup.py`, whose `brief` writes the whole brief;
  - `plugins/audit/scripts/manifest/audit-task.py`, for the filing verb and `done --from-return`;
  - `plugins/audit/agents/audit-executor.md`, `plugins/audit/agents/audit-reviewer.md`;
  - the task prose, `plugins/audit/scripts/_refs.py` and `PLUGIN-BUILD-GUIDE.md`;
  - the tests of both scripts.
- **The reviewer's write.** `audit-reviewer.md` gains one *May* line: one call of the filing verb.
  Its *Must not* keeps "anything that writes", with that call as the only exception. The filing
  verb takes the task id and the role and no path, and derives the one file it writes. Its tests
  pin three things: a path-like argument is refused; a malformed return writes nothing; and the
  written path equals the derived one. Those cases are what holds the write to the reviewer's own
  return. That the reviewer runs nothing else that writes stays a followed rule, unenforced, as it is
  today (C3, *Guarantees*).
- **Target** (`python3 tools/stream-cost.py <session>/stream.jsonl`):
  - no `brief for audit:audit-*` row above 200 tokens in `largest outputs`;
  - the main-loop output pool at most 5000 tokens per task (`feature-C-1`: 14031; predicted 4472
    for one task once T4 has landed too, C3's *Confirming reading*);
  - the main context's task tokens per task at most 11000 (`feature-C-1`: 25455; predicted 9547 for
    one task, with T4).
- **Confirming session:** the after-study.

### T4 — The task cycle in five main-loop requests (C7)

- **Files:** `plugins/audit/scripts/manifest/audit-task.py`; the governance scripts it calls; the task
  prose; tests.
- **Target:** at most 5 plan, gate and close requests per task, and at most `7 + 5N` main-loop
  requests before sign-off, read from `per stage, as billed` → `req`. `feature-C-1` made 8 per task,
  two of them one-offs (section 1.1).
- **Confirming session:** the after-study.

### T5 — Calibrate the model from the baseline sessions

- **Files:** `docs/research/pipeline-cost-design.md`, an addendum.
- **What:** read T1's new rows off the whole-feature arm C sessions at the pinned commit:
  - per-task requests and `S`;
  - planning invocations and command-body injections;
  - the main loop's longest gap;
  - each later dispatch's `start_cR`.

  Then replace each assumption of section 1.4 with its reading, and re-compute the predictions.
- **Target:** no assumption in section 1.4 is left without its reading beside it.
- **Confirming session:** the baseline sessions themselves, as section 7 says.

### T6 — Only if the user decides: `review.perTask` (C5)

- **Files:** the config schema, `_config_rules.py`, the panel's control, the reviewer step's prose and
  the doctor's line, as R8 lists.
- **Target:** reviewer contexts per session in `contexts:` equal the number of tasks the gate
  selects.
- **Confirming session:** an arm C session with the key set, plus R8's quality count.

## 7. The confirming benchmark, in the harness's terms

**Before.** The whole-feature study's arm C sessions are `whole-C-3`, `whole-C-1` and `whole-C-2-r`, in
`<h2>/order.json`'s seeded order. They run at `pins.json` → `pluginSha` `f7eaade4`, whose plugin is byte
for byte the one these figures were taken at: `git diff --stat f7eaade4 7b489337 -- plugins/audit`
prints nothing. On
2026-10-07 no arm C session of that study was valid yet: `whole-C-2` is in `<x2>/invalid.jsonl`. So
the baseline and T5's calibration both wait on them.

**After.** Use a copy of `<h2>` that changes `benchlib.EXPERIMENTS` and `pins.json` → `pluginSha`, and
nothing else. That follows the harness's own precedent: v2 is "a copy of `../bench-feature/` extended,
not an edit of it". A suggested name is `fixtures/bench-feature-cost`. Its records go to its own
experiments folder. It runs arm C only, at least three sessions as the protocol fixes per arm
(`benchmark-feature-design.md`, section 6), in a seeded order, at the commit that lands T2 to T4. One
study is enough for every target, because each target reads its own row of `stream-cost.py`.

**This study's protocol is the whole-feature benchmark's, and it lands with that benchmark's phase,
not with this one** (section 0). Until that phase merges, the sections cited here are read at
`a289dcbb`.

| Target | Row read per session |
|---|---|
| T2 | the summed `Read <plugin>/reference/…` tokens; run `$write` |
| T3 | `largest outputs`; `output pool, measured: main loop` per task; `contexts:` → `main`, `task` |
| T4 | `per stage, as billed` → `req` per task |
| the whole set | `all models priced`, set beside section 5's prediction for the session's task count |

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

**Cost.** `python3 <h2>/estimate.py` printed the arm C range per session on 2026-10-07
(`benchmark-feature-design.md`, section 8). Re-run it before agreeing a budget. It does not model
this design's saving.

## 8. Decisions that are the user's

1. **Per-task reviewer gating (C5).**
   - (a) Keep the review on every task.
   - (b) Add `review.perTask` with a default of `always` (minor), gating on R8's two computed
     conditions only: a `redFirst` that did not come back `proved`, and a gate row that disagrees with
     the executor's return. R8's `risky` arm as written also gates on the self-declared `task.risk`
     (C5, *Guarantees*).
   - (c) Ship a gated default (major).

   **Recommendation: (a).** If the saving is wanted, take (b), never on the self-declared `risk`, and
   never with a default change inside the major line.
2. **The light path (C1).**
   - (a) Do not build it.
   - (b) Build it behind a key that defaults off. The README's enforced row then has to say it does not
     cover light-path work.
   - (c) Build it on by default (major).

   **Recommendation: (a).** C1 in section 3 predicts that its inline part costs more than it saves
   once C3 lands, and it is the one option that gives up an enforced row.
3. **Where a filed return lives (C3).**
   - (a) The committed evidence directory, so an executor's claim is part of the record a clone
     receives.
   - (b) Session scratch under `stateDir`.

   **Recommendation: (a).** It is what lets a later checker compare a claim with its gate row. The cost
   is larger commits: in `feature-C-1` the hand-backs were 6142 and 3550 bytes (`largest outputs`).

   Either way the reviewer gains one write, through the filing verb, held to its own return (C3,
   *Guarantees*). Neither option touches the README's enforced row "the reviewer cannot edit", because
   the `tools:` line that holds it gains nothing. What (b) would add is that a stray reviewer write
   could not ride into the close commit with the evidence directory. Its trade is that the reviewer's
   findings then reach the record only through what the close writes.
4. **The spend on the after-study.** **Recommendation:** run the whole-feature arm C sessions first,
   because they are both the baseline and T5's calibration. Then implement, then run the after-study.
5. **Main-loop TTL guidance (C6a).** Whether the plugin can set it is **unknown**. The host facts name
   the settings and environment variables a user sets, and nothing says a plugin can ship one
   (section 9). Which TTL a user's main loop gets also follows their billing (section 1.4).
   **Recommendation:** document the trade with its arithmetic, and recommend no value until T5 has
   measured the gaps.

## 9. Unknowns, and the choice that depends on each

Each is listed as not documented in the host facts gathered from the official documentation on
2026-10-07, except the one whose entry says otherwise:

- **Whether `${CLAUDE_PLUGIN_ROOT}` or `$ARGUMENTS` substitute inside a plugin command's `!`
  injection.** C2 and C8 use a tool call in its place, at the cost of one main-loop request. A probe
  would settle it: a scratch plugin command whose body holds an `!` line echoing both values, invoked
  once headless in a scratch directory. The session's first user message shows whether either was
  substituted. A probe is a paid session, so it was designed and not run.
- **Whether a plugin can ship a default `promptCacheTtl`.** C6a.
- **Which TTL a given user's main loop runs at.** The host facts document the default per billing:
  one hour on a subscription within its plan's included usage, five minutes on usage credits, an API
  key or a cloud provider. What the plugin cannot know is which applies to a user. Every dollar
  prediction here assumes one hour (section 1.4), and C6a is the difference.
- **Whether a plugin's agent can be spawned as a fork.** C6b, which is rejected on its guarantees
  either way.
- **The order of a subagent's initial context.** C6c.
- **Whether a command invoked several times injects its body each time, and whether the model re-reads
  reference files on a second command in one session.** The host facts say a command's instructions
  enter "at the point of invocation". How often that happens in arm C is the multiplier for C8.

And from the records:

- **Single-task records only.** The per-task request split is an inference from one session's tool
  calls. Whether its two one-off requests recur is unmeasured.
- **The divisor of 2.63 was calibrated on this prose.** Every target is in bytes, so the divisor moves
  only the dollar predictions.

## 10. Re-deriving every figure

| Figure | Command |
|---|---|
| stage, class, row and context figures | `python3 tools/stream-cost.py <record>/stream.jsonl` (`--json` for `requests` and `items`), from a checkout of the commit section 0 names |
| bytes read first per entry, at a ref | `python3 tools/measure-context.py --ref 7b489337 --ref f7eaade4 --bytes-per-token 2.63` |
| `/audit:task`'s entry total, until T1 adds the entry | `python3 -c "import importlib.util as u; s=u.spec_from_file_location('mc','tools/measure-context.py'); m=u.module_from_spec(s); s.loader.exec_module(m); src,_=m.git_source('7b489337'); print(sum(r['bytes'] for r in m.entry_rows(src,'command','commands/task.md',None)))"` |
| the main loop's tool calls per request | the snippet in section 1.1 |
| the rates | `git show 7b489337:plugins/audit/scripts/usage/_usage_core.py \| grep -n claude-opus-5-5` |
| bytes per heading of a reference or command file | below |
| the earlier backlog's state | section 0.1's commands, which read the working tree; their answers were taken at `7b489337` |

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
