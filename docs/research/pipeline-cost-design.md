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
`experiments/bench-feature-v2` and `<h2>` is `fixtures/bench-feature-v2`, the whole-feature benchmark
whose protocol is `docs/research/benchmark-feature-design.md`. Commands run from this
repository's root. Prices are the plugin's shipped table, `_usage_core.DEFAULT_PRICING`. For
`claude-opus-5-5` the rates per million tokens are: input 4.0, output 20.0, five-minute write 5.0,
one-hour write 8.0, cache read 0.2. The reviewer in `feature-C-1` ran on a model that resolves to the
`claude-sonnet-5` row: five-minute write 2.5, cache read 0.2, output 10.0. Bytes become tokens at the
calibrated 2.63 bytes per token (the analysis, section 6.1).

**Every session here was run once.** Each figure from a session is one observation of that session.
None is a rate.

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
| task class total | `0.7742` | same |
| file class total | `0.2211` | same |
| reference prose written once | 57417 tokens, derived: 21913 + 21875 + 13629 | `largest cache writes`, the three `Read <plugin>/reference/…` rows |
| later main-loop requests that re-read it | 12 | the `reads` column of those rows |
| what those rows cost | `0.5971`, derived: 0.2279 + 0.2275 + 0.1417 | their `$total` |
| run-class tokens a further main-loop request reads | 79461 | `contexts:` → `main`, `run` |
| task-class tokens left in the main loop after the task | 25010 | `contexts:` → `main`, `task` |
| price of one more request, main loop / executor / reviewer | `0.0210` / `0.0063` / `0.0050` | `contexts:` → `$/request` |
| main-loop requests | orient 2, plan 5, gate 3, close 5 | `per stage, as billed` → `req` |
| agent starts | executor 16952 tokens, five-minute write on opus (`0.0848`); reviewer 15878, on the sonnet row (`0.0397`) | `largest cache writes`, `agent start` rows |
| briefs typed by the main loop | 2840 and 2817 output tokens (`0.0568`, `0.0563`) | `largest outputs` |
| main-loop output | 14031 tokens | `output pool, measured: main loop` |

**Which main-loop requests are per task (inference).** The main loop's tool calls were listed from the
stream:

```
python3 -c "import json,sys
for l in open(sys.argv[1]):
    e=json.loads(l)
    if e.get('type')!='assistant' or e.get('parent_tool_use_id'): continue
    for c in e['message']['content']:
        if c.get('type')=='tool_use': print(e['message']['id'][-6:], c['name'], str(c['input'])[:90])
" <x>/feature-C-1/stream.jsonl
```

After the request that wrote the prose, the run-level requests are the manifest read, the lock, the
lock release and the report. Eight are per task: the task start, the executor dispatch, the gate run,
the stamp comparison, the reviewer dispatch, the commit, and two attempts at the close. The second
close attempt happened once, in one session. The pilot's main loop made 17 requests
(`python3 tools/stream-cost.py <p>/stream.jsonl`, the `req` column), so the shape varies between
runs.

### 1.2 The formulas

Notation: `w` is the one-hour write rate 8.0e-6, `r` the cache-read rate 0.2e-6 and `o` the output
rate 20e-6, each per token for the main loop's model. `N` is the number of tasks a run executes.

- **Prose.** `T` prose tokens are written once and re-read by every later main-loop request:
  `cost = T × (w + r × m)`, with `m = 4 + 8N` later requests. Check against `feature-C-1`, where
  N = 1: 57417 × (8.0 + 0.2 × 12) / 10^6 = `0.5971`, which equals the measured rows.
- **Run class.** `0.5406 + 0.0109 + 0.2017 × m / 12`. That is the measured write and output, plus the
  measured carry scaled by the request count.
- **Task class.** `0.7742 × N + c × r × (8 × N(N−1)/2 + 2 × (N−1))`, with `c` = 25010 tokens. Each
  task's eight requests re-read every earlier task's content, and the release and the report re-read
  every task's. This is the analysis's section 4 inference written as a formula. No recorded session
  ran more than one task.
- **File class.** `0.2211 × N`. This assumes every task is the size of `feature-C-1`'s task.

**Prediction, today's pipeline:**

| | run | task | file | total |
|---|---|---|---|---|
| N = 1 | `0.7532` | `0.7742` | `0.2211` | `1.7485` (measured: `1.748411`) |
| N = 5 | `1.2911` | `4.3112` | `1.1055` | `6.7077` |

The task class grows with the square of `N`. That term is `0.4002` at N = 5 (derived:
25010 × 0.2e-6 × 8 × 10), and no single-task record can show it.

### 1.3 What a kilobyte costs, by where it sits

Derived from the rates and the request counts above. This is why the main loop's prose comes first:

| Where the bytes are | Price per 1000 bytes (380 tokens) | Arithmetic |
|---|---|---|
| main-loop prose, N = 1 | `0.00395` | 380.2 × (8.0 + 0.2 × 12) / 10^6 |
| main-loop prose, N = 5 | `0.00639` | 380.2 × (8.0 + 0.2 × 44) / 10^6 |
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

- removed: the executor start (16952 × 5.0 = `0.0848`), its brief (2840 × 20 = `0.0568` typed, plus
  `0.0226` carried by the main loop), and its hand-back (3125 × 20 = `0.0625` typed, plus `0.0260`
  carried). Together `0.2527`.
- added: three things.
  - The executor's work, 14561 tokens (derived: 31513 − 16952), is written at the main loop's one-hour
    rate: 14561 × (8.0 − 5.0) = `0.0437`.
  - Its requests re-read the main loop's prefix instead of their own: (9 × 85269 + 27695 − 180263) ×
    0.2 = `0.1229`. 85269 is what the main loop read on its first request after the dispatch.
  - Later main-loop requests carry the work: 14561 × 8 × 0.2 = `0.0233`.

  Together `0.1900`.
- net: `0.0627` per task. With an executor on the sonnet row the net is `−0.1191`, a cost: the work's
  output is then written at the main loop's output rate, twice the executor's.

Once C3 lands, the brief and hand-back rows are gone whichever path runs. The inline part then saves
the executor start alone, against the same additions: 0.0848 − 0.1900 = `−0.1052` per task, a cost.

The per-task reviewer is skipped too, which adds C5's `0.2024`. That gives a prediction of `0.2651` at
N = 1 and `0.7250` at N = 5 with an opus executor, and `0.0833` and `−0.1842` with a sonnet executor. At
N = 5 every inline request also re-reads the earlier tasks' content: 9 × 25010 × 0.2 × 10 = `0.4502`.

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

Bytes are per heading. `execute-task.md` is a single heading, so it was split by line ranges at HEAD
(`7b489337c06d`). Section 10 has the command.

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

`tools/measure-context.py --ref HEAD` prints 153701 bytes read first, the sum of the three files. The
table's 153704 counts one more newline per file.

**Prediction.** The target is 80000 bytes read first for `/audit:run`: the keep class plus about two
kilobytes. Where a maintainer section leaves, one sentence stays: the rule and the script that
enforces it. That removes 73701 bytes, or 28023 tokens:

- N = 1: 28023 × (8.0 + 0.2 × 12) / 10^6 = `0.2914`;
- N = 5: 28023 × (8.0 + 0.2 × 44) / 10^6 = `0.4708`.

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

**Prediction, per task, from `feature-C-1`'s rows (`--json` → `items` and `requests`):**

| Part | Arithmetic | Saving |
|---|---|---|
| briefs no longer typed | (2840 + 2817 − 120) × 20 / 10^6; 120 tokens is the estimated cost of two short hand-off prompts | `0.1107` |
| briefs no longer carried by the main loop | 0.0192 + 0.0034 + 0.0174 + 0.0017, less 120 × 10.4 / 10^6 | `0.0405` |
| hand-backs reduced to one line in the main loop | 0.0221 + 0.0039 + 0.0117 + 0.0012, less 160 × 9.2 / 10^6 | `0.0374` |
| each agent reads its brief, one extra request each | −(14112 + 13061) × 0.2 / 10^6 | `−0.0054` |
| the close no longer composes the outcome | (1723 + 1769 − 100) × 20 / 10^6 | `0.0678` |
| the close's tool results and text, no longer carried | 0.0158 + 0.0004 + 0.0105 + 0.0005 + 0.0133 + 0.0007 + 0.0127 + 0.0003, less 400 × 8.4 / 10^6 | `0.0508` |
| **per task** | | **`0.3019`** |

The task-class tokens the main loop keeps fall from 25010 to 10331 per task. That is derived:
25010 − (2395 + 2180) − (2764 + 1466) − (1978 + 1318) − (1667 + 1591) + (120 + 160 + 300 + 100). At
N = 5 the square term shrinks with it: 5 × 0.3019 + 14679 × 0.2e-6 × 88 = `1.7677`. The close's 1769
tokens came from its second attempt, which `feature-C-1` made once; without it the per-task figure is
`0.0354` lower.

**Guarantees.** None is weakened, and sentences in which the task prose admits that nothing checks
something are answered:

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

C3 also adds one single point of failure: a defect in the brief script briefs every executor wrong. The
script's selftests and the provenance it prints into each brief are what hold against that.

**Maintenance.** About 13 kilobytes of prose become one script and its selftests. The lints that pin
the brief's prose are re-pointed at the script's output. `return_shape_drift` reads `execute-task.md`
today (`scripts/_refs.py:1275`).

**COMPATIBILITY.md.** The new flags are additive. The filed return is a new record whose shape is
outside the contract.

**Confirming reading.**

- `largest outputs` holds no `brief for audit:audit-*` row above 200 tokens.
- `output pool, measured: main loop` is at most 5000 tokens per task. For one task the prediction is
  4982, derived: 14031 − 5657 − 3392.
- `contexts:` → `main`, `task` divided by the task count is at most 11000.

**Effort, blast radius, risk.** It touches one extended script, a new verb and flag in
`audit-task.py`, both agent prompts, the task prose, `_refs.py`, and `PLUGIN-BUILD-GUIDE.md`. The
enforced and followed tables lose no row, and the admissions that nothing checks a return's shape or
its stamp are answered by an exit code.

### C4 — Rules a script already enforces, deleted from the prose

**What.** A sentence stays when it tells the model what to do. A paragraph that explains what a script
does for the model moves to `PLUGIN-BUILD-GUIDE.md` or to the script's docstring. One sentence is left
in its place: the rule, and the script that enforces it. The scope is the maintainer class of C2's
table, 23089 bytes.

**Prediction.** 8779 tokens: `0.0913` at N = 1 and `0.1475` at N = 5, from the section 1.2 prose
formula. This is part of C2's cut, not an addition to it. The agents' own prompts qualify too, but at
section 1.3's prices a kilobyte there is worth `0.00251` per executor dispatch, against `0.00395` to
`0.00639` for the same kilobyte in the main loop.

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

That is `0.2024`. With every task skipped at N = 5, the prediction is
5 × 0.2024 + 3646 × 0.2e-6 × 80 = `1.0704`.

After C3 and C7 the brief and the hand-back are already gone. The marginal saving then falls to the
stage plus one request at the smaller prefix: 0.0957 + 49055 × 0.2e-6 = `0.1055` per task. 49055 is
the 41055 run tokens of section 5 plus about 8000 of the task's own, an estimate.

**Guarantees.** The per-task claim-to-task binding (`execute-task.md:313-315`) becomes conditional.
The record stays honest: `not-asked` needs a basis, and sign-off lists unanswered tasks. One
structural weakness stands: `task.risk` is written by whoever plans the task. In the whole-feature
benchmark that is the session whose work would be reviewed, so the subject chooses its own review. R8's
`risky` arm gates on computed properties instead: a red-first that did not come back `proved`, or a
return that disagrees with its row. C3 is what makes those computable by a script.

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
  were at the five-minute rate. At N = 5 the main loop writes 194845 tokens (derived: 9922 + 57648 +
  5 × 25455). The prediction is 194845 × 3.0 / 10^6 = `0.5845`, if no gap ever passes five minutes.
  One lapse late in that run re-writes the prefix: 179501 × 5.0 / 10^6 = `0.8975`, against `0.0359`
  to read it. Whether a plugin can set the main loop's TTL is **unknown** (section 9). This is the
  user's setting and the user's bet on their gaps; it is not a plugin change.
- **b. A fork for the reviewer.** A fork's first request reads the parent's cache. It saves the
  reviewer's start, 15878 × 2.5 / 10^6 = `0.0397`. But every fork request reads the whole main prefix
  on the parent's model. Its output is priced on opus, and its work is written at opus rates. The
  prediction is `−0.0653` per task: it costs more. A fork also "sees the same system prompt, tools,
  model" as the parent (host facts), so the enforced row "the reviewer cannot edit" goes, along with
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

**What.** In `feature-C-1` the task took eight main-loop requests (inference, section 1.1). Composite
verbs fold them into five:

1. start, plus the brief;
2. dispatch;
3. the recorded gate, the stamp comparison and the reviewer brief;
4. dispatch the reviewer;
5. the commit, plus `done --from-return`.

Each composite calls the existing verbs in the existing order, stops at the first refusal, and prints
it.

**Why the evidence points here.** A main-loop request costs `0.0210` against the executor's `0.0063`
(`contexts:`). The main loop is the dearest place in the pipeline to spend a round trip.

**Prediction.** The removed requests are `feature-C-1`'s stamp comparison and its two close attempts:
(90428 + 96761 + 97956) × 0.2 / 10^6 = `0.0570` of reads, plus the comparison's output and rows,
`0.0126` + `0.0099`. That is `0.0795` per task. At N = 5: 5 × 0.0795 + 3 × 25010 × 0.2e-6 × 10 =
`0.5477`. Without the second close attempt, the figures are `0.0599` and `0.3997`. In wall clock, the
main loop's stages took 119.0 s over 15 requests (derived from `wall_s`: 6.2 + 37.3 + 31.4 + 44.1), so
three fewer requests is about 24 s per task. That is a crude prediction: a request's wall includes the
gate run it starts.

**Guarantees.** None weakened. The per-task order becomes a verb's order rather than a paragraph's.

**COMPATIBILITY.md.** New verbs are additive.

**Confirming reading.** `per stage, as billed` → `req`: plan, gate and close requests per task, at
most 5.

**Effort, blast radius, risk.** It touches `audit-task.py`, plus the existing governance scripts it
calls but does not re-implement. No row of either table changes.

### C8 — Verb-scoped command reads (pointed to by the evidence)

**What.** `/audit:phase` tells the model to read all four reference files before it chooses its verb
(`commands/phase.md:9-13`). So `/audit:phase add`, a structural write, loads 242068 bytes:
`python3 tools/measure-context.py --ref HEAD`, the `/audit:phase` total. `/audit:task` reads
`manifest-conventions.md` first (`commands/task.md:51`), and its body carries every one of its verbs:
74659 bytes, `wc -c plugins/audit/commands/task.md`.

C8 makes the verb choice first and the read second. Each verb's prose goes in a file the dispatcher
names, which is the supporting-file pattern the skills documentation describes. Injecting the verb's
section through `!` command substitution would save the extra read, but it depends on a substitution
the docs do not state (section 9).

**Prediction, per invocation.** The targets are 30000 bytes for `/audit:phase add`, which needs its own
section and the conventions it writes against, and 45000 for `/audit:task add`.

| Invocation | Tokens removed | Carried by 20 later requests | Carried by 50 |
|---|---|---|---|
| `/audit:phase add` | 80634, derived: (242068 − 30000) / 2.63 | `0.9676` | `1.4514` |
| `/audit:task add` | 24943, derived: (110599 − 45000) / 2.63; 110599 is the `total` of `wc -c plugins/audit/commands/task.md plugins/audit/reference/manifest-conventions.md` | `0.2993` | `0.4490` |

At N = 1 in the `/audit:run` shape the saving is zero, because that command plans nothing. In the
whole-feature benchmark's arm C, C8 is where the session may differ most from `feature-C-1`. A dollar
figure for arm C's planning is not predicted, because it needs the invocation count.

**Guarantees.** None. The verb dispatch is already lexical (`commands/phase.md`, *0. Which verb*).

**COMPATIBILITY.md.** None: the command names stay.

**Confirming reading.** The plugin command-body injections and reference reads per session. Today's
tool does not count them; T1 adds the count.

### Considered and set aside

- **A fresh main loop per task.** This trades the square term for a run class paid per task. After the
  recommended change, break-even is at about 45 tasks. Derived: 2 × 0.2334 / (10331 × 0.2e-6 × 5),
  where 0.2334 is the run write once the prose is cut (section 5). Below that, one main loop is cheaper.
- **A cheaper model for the main loop**, through a command's `model:` frontmatter. The main loop holds
  every followed rule. And per the host facts, a model switch mid-session re-reads the whole history
  with no cache hit. The model is the user's choice, not a cost lever this design takes.
- **`omitClaudeMd`.** This is R5, unchanged. The executor needs the project's `CLAUDE.md`, as R5
  already said.

## 4. Side by side

All savings are predictions in USD, from section 1's model. "Rows" means rows of the README's
enforced and followed tables.

| | N = 1 | N = 5 | Guarantees | Maintenance | COMPATIBILITY.md | Verdict |
|---|---|---|---|---|---|---|
| C1 light path, executor on opus / on sonnet | `0.2651` / `0.0833` | `0.7250` / `−0.1842` | an enforced row stops covering the work; isolation lost | a second execution path | key additive; default on is major | not recommended |
| C2 by verb, state and moment | `0.2914` | `0.4708` | none, if every followed row stays reachable | more files; lints re-pointed | none | **recommended** |
| C3 computed brief, filed return | `0.3019` | `1.7677` | none; a return's shape and stamp become checked | prose becomes a tested script | additive | **recommended** |
| C4 enforced restatements out | `0.0913` | `0.1475` | none, by construction | lower | none | **recommended**, inside C2 |
| C5 reviewer by risk | `0.2024` per skipped task | `1.0704` if every task skips | one followed check narrowed | a config key | key additive; gated default is major | the user's (section 8) |
| C6a main-loop TTL | `0.2791` | `0.5845` | none | none | none | the user's setting; measure gaps first |
| C6b fork reviewer | `−0.0653` per task | | an enforced row lost | | | rejected |
| C6c shared agent starts | `0` | up to `0.3911` | none | none | none | measure; nothing to build |
| C7 five requests per task | `0.0795` | `0.5477` | none | composite verbs | additive | **recommended** |
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
kilobytes of residual sentences. That figure is an estimate. The remaining changes are:

- requests per task go from 8 to 5;
- task tokens left in the main loop go from 25010 to 10331 per task;
- the per-task class falls by C3's `0.3019`, and by C7's `0.0264` that is not already in the run
  class.

| | run | task | file | total | today | saving |
|---|---|---|---|---|---|---|
| N = 1 | `0.3291` | `0.4460` | `0.2211` | `0.9962` | `1.7485` | `0.7523`, 43.0% |
| N = 5 | `0.4934` | `2.3497` | `1.1055` | `3.9486` | `6.7077` | `2.7592`, 41.1% |

The run figures come from three quantities. The run write becomes 0.5406 − 38406 × 8.0e-6 = `0.2334`,
where 38406 is derived as 57417 − 50000 / 2.63. A further request reads 41055 run tokens instead of
79461. And there are `4 + 5N` later requests. The model is anchored on `feature-C-1`'s prose, 151022
bytes, which is 2679 fewer than HEAD's. That makes it conservative by `0.0106` at N = 1, derived:
2679 / 2.63 × 10.4e-6.

**The phase run form, prose only, with `S` = 6 assumed.** Today `/audit:phase` reads 242068 bytes up
front, and every request after that carries them. After the change it reads 64470 bytes during the
tasks: the run section of `phase.md`, 14470 by the section 10 command, plus the 50000 above. It reads
`phase-signoff.md`'s 48598 bytes only at sign-off. The prediction:

- N = 1: `1.0677` today and `0.4396` after;
- N = 5: `1.6567` today and `0.5377` after.

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
review. C5 stays the user's decision.

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
- **Target** (`python3 tools/measure-context.py --ref <commit> --bytes-per-token 2.63`):

  | Entry | Read first, at most | At HEAD |
  |---|---|---|
  | `/audit:run` | 80000 bytes | 153701 |
  | `/audit:phase add` | 30000 | 242068 |
  | `/audit:task add` | 45000 | 110599 (`wc -c`, C8) |
  | `/audit:phase` run form, before sign-off | 95000 | 242068 |

  A new lint checks that every followed row's "Stated in" resolves to a heading in a file some
  command reads, and it is shown red before it is trusted. A ceiling gate, `measure-context.py
  --gate`, holds those maxima in CI. The prose grew between `v3.1.0` and `main` (the analysis,
  section 6), so without a gate the cut would rot.
- **Confirming session:** the after-study in section 7. It reads the `Read <plugin>/reference/…` tokens
  per session and the run class `$write`.

### T3 — Computed briefs and filed returns (C3)

- **Files:**
  - `plugins/audit/scripts/status/audit-lookup.py`, whose `brief` writes the whole brief;
  - `plugins/audit/scripts/manifest/audit-task.py`, for the filing verb and `done --from-return`;
  - `plugins/audit/agents/audit-executor.md`, `plugins/audit/agents/audit-reviewer.md`;
  - the task prose, `plugins/audit/scripts/_refs.py` and `PLUGIN-BUILD-GUIDE.md`;
  - the tests of both scripts.
- **Target** (`python3 tools/stream-cost.py <session>/stream.jsonl`):
  - no `brief for audit:audit-*` row above 200 tokens in `largest outputs`;
  - the main-loop output pool at most 5000 tokens per task (`feature-C-1`: 14031);
  - the main context's task tokens per task at most 11000 (`feature-C-1`: 25010).
- **Confirming session:** the after-study.

### T4 — The task cycle in five main-loop requests (C7)

- **Files:** `plugins/audit/scripts/manifest/audit-task.py`; the governance scripts it calls; the task
  prose; tests.
- **Target:** at most 5 plan, gate and close requests per task, and at most `7 + 5N` main-loop
  requests before sign-off, read from `per stage, as billed` → `req`. `feature-C-1` made 8 per task.
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
for byte this design's HEAD: `git diff --stat f7eaade4 HEAD -- plugins/audit` prints nothing. On
2026-10-07 no arm C session of that study was valid yet: `whole-C-2` is in `<x2>/invalid.jsonl`. So
the baseline and T5's calibration both wait on them.

**After.** Use a copy of `<h2>` that changes `benchlib.EXPERIMENTS` and `pins.json` → `pluginSha`, and
nothing else. That follows the harness's own precedent: v2 is "a copy of `../bench-feature/` extended,
not an edit of it". A suggested name is `fixtures/bench-feature-cost`. Its records go to its own
experiments folder. It runs arm C only, at least three sessions as the protocol fixes per arm
(benchmark-feature-design.md, section 6), in a seeded order, at the commit that lands T2 to T4. One
study is enough for every target, because each target reads its own row of `stream-cost.py`.

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
(benchmark-feature-design.md, section 8). Re-run it before agreeing a budget. It does not model this
design's saving.

## 8. Decisions that are the user's

1. **Per-task reviewer gating (C5).**
   - (a) Keep the review on every task.
   - (b) Add `review.perTask` with a default of `always` (minor), gating on computed properties.
   - (c) Ship a gated default (major).

   **Recommendation: (a).** If the saving is wanted, take (b), never on the self-declared `risk` alone,
   and never with a default change inside the major line.
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
4. **The spend on the after-study.** **Recommendation:** run the whole-feature arm C sessions first,
   because they are both the baseline and T5's calibration. Then implement, then run the after-study.
5. **Main-loop TTL guidance (C6a).** The plugin cannot set it; the documentation does not say it can.
   **Recommendation:** document the trade with its arithmetic, and recommend no value until T5 has
   measured the gaps.

## 9. Unknowns, and the choice that depends on each

Each is listed as not documented in the host facts gathered from the official documentation on
2026-10-07:

- **Whether `${CLAUDE_PLUGIN_ROOT}` or `$ARGUMENTS` substitute inside a plugin command's `!`
  injection.** C2 and C8 use a tool call in its place, at the cost of one main-loop request. A probe
  would settle it: a scratch plugin command whose body holds an `!` line echoing both values, invoked
  once headless in a scratch directory. The session's first user message shows whether either was
  substituted. A probe is a paid session, so it was designed and not run.
- **Whether a plugin can ship a default `promptCacheTtl`.** C6a.
- **Whether a plugin's agent can be spawned as a fork.** C6b, which is rejected on its guarantees
  either way.
- **The order of a subagent's initial context.** C6c.
- **Whether a command invoked several times injects its body each time, and whether the model re-reads
  reference files on a second command in one session.** The host facts say a command's instructions
  enter "at the point of invocation". How often that happens in arm C is the multiplier for C8.

And from the records:

- **Single-task records only.** The per-task request split is an inference from one session's tool
  calls.
- **The divisor of 2.63 was calibrated on this prose.** Every target is in bytes, so the divisor moves
  only the dollar predictions.

## 10. Re-deriving every figure

| Figure | Command |
|---|---|
| stage, class, row and context figures | `python3 tools/stream-cost.py <record>/stream.jsonl` (`--json` for `requests` and `items`) |
| bytes read first per entry, at a ref | `python3 tools/measure-context.py --ref HEAD --ref f7eaade4 --bytes-per-token 2.63` |
| the main loop's tool calls per request | the snippet in section 1.1 |
| the rates | `grep -n claude-opus-5-5 plugins/audit/scripts/usage/_usage_core.py` |
| bytes per heading of a reference or command file | below |
| the earlier backlog's state | section 0.1's commands |

```
python3 - plugins/audit/reference/orchestrator.md <<'EOF'
import re, sys
L = open(sys.argv[1], encoding="utf-8").read().split("\n")
hs = [i for i, l in enumerate(L) if re.match(r"^#{1,3} ", l)]
print(sum(len(x.encode()) + 1 for x in L[:hs[0]]), "(before the first heading)")
for k, i in enumerate(hs):
    j = hs[k + 1] if k + 1 < len(hs) else len(L)
    print(sum(len(x.encode()) + 1 for x in L[i:j]), L[i])
EOF
```

For `execute-task.md`, sum the same expression over the line ranges section 3 names for C2's
classes, as `L[a - 1:z]`.
