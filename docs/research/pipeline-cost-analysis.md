# Pipeline cost analysis — what a run pays for, and why

Two observations were published without an explanation:

1. **The pilot's main loop before any dispatch was the largest share of its cost**
   ([pipeline-pilot.md](pipeline-pilot.md), section 4).
2. **The plugin arm of the feature benchmark cost several times the plain arm on a task both
   solved** ([benchmark-results.md](benchmark-results.md), section 2.4).

This document explains both with numbers. It attributes the recorded sessions' tokens, prices and
time to pipeline stages and to the content that filled each context, and it measures the prose each
pipeline step loads at the published tag and at `main`. Everything was done offline with tools
added for it, and no model call was made. The protocol and the outcome tables of those sessions are
in [benchmark-design.md](benchmark-design.md) and the two documents above; they are not repeated.

**Every session here was run once.** Each session named below, plugin or plain, was measured once,
so every figure below describes one session. None of them is a rate.

## 0. How to read this

| Label | Means |
|---|---|
| **measured** | printed by a tool from a session record or a git ref, with the command beside it |
| **estimate** | printed by a tool, and labelled an estimate by the tool itself, with the rule it used |
| **derived** | arithmetic on printed figures; the arithmetic is written out |
| **inference** | reasoning from the above; not evidence |

Commands run from this repository's root. Session records live in the internal repository's analysis
folder: `<x>` is `experiments/bench-feature` there, and `<p>` is
`experiments/p101-pilot-2026-10-06/run`. The plugin session of the feature benchmark is
`<x>/feature-C-1` and the plain sessions are `<x>/feature-A-1` and `<x>/feature-A-2`. The pilot's
record is `<p>`.

## 1. The instruments

**`python3 tools/stream-cost.py <stream.jsonl>`** reads one recorded `stream-json` session and
prints two views of it.

- **By stage, as billed.** Every request's tokens go to the stage of that request, priced with the
  plugin's own shipped table (`_usage_core.DEFAULT_PRICING`). The stages are `orient`, `plan`,
  `executor`, `gate`, `reviewer` and `close`, plus `main` for a session that dispatches nothing. The
  tool's docstring gives the rule for each.
- **By content.** Each cache write is attributed to its source: a file read, a command's output, a
  hand-back, the session's start. Each source is charged what writing it cost plus what every
  later read of it cost. The results are totalled by the stage the content came from and by class:
  `run` (fixed per run), `task` (per task) and `file` (per file the work touches).

The content view rests on an identity that the tool checks on every request. Within one context,
a request reads from cache what the first request read, plus everything written since. When the
identity holds, a write's carrying cost is a count of reads. Two things the stream lacks are
rebuilt from the result event. One is each subagent's final request, the one that writes its
hand-back. The other is the true output counts, since the stream carries only emit-time counts.
The tool prints the basis for both.

**`python3 tools/measure-context.py --ref <ref> [--ref <ref>]`** lists what each step on the
pipeline's path loads before it does any work:

- for a command: the command body, and the files its up-front read paragraph names;
- for an agent: its system prompt and the skills it preloads;
- the always-on listing.

Bytes are measured. Tokens are bytes divided by a stated divisor, labelled an estimate.

Both tools carry a `--selftest` that `tools/sweep-selftests.py` runs. Stream attribution is proved
on a hand-built session whose answer was worked out by hand, and on a twin of that session that
must not move a token between stages.

### 1.1 How far the readings can be trusted

Measured on every session here, each with `python3 tools/stream-cost.py <record>/stream.jsonl`. The
block is condensed from each report's `pricing:` lines:

```
<x>/feature-C-1   claude-opus-5-5   priced=1.652756 costUSD=1.652756  agree
                  claude-sonnet-5-5 priced=0.095655 costUSD=0.095655  agree
<p>               claude-opus-5-5   priced=1.156809 costUSD=1.156809  agree
                  claude-sonnet-5-5 priced=0.130942 costUSD=0.130942  agree
<x>/feature-A-1   claude-opus-5-5   priced=0.284359 costUSD=0.284359  agree
<x>/feature-A-2   claude-opus-5-5   priced=0.311679 costUSD=0.311679  agree
```

The `breaks` column of each report's `contexts:` section read 0 for every context.

On 2026-10-07 the shipped table reproduced every model's `costUSD` to the printed digit, once each
write was priced at the TTL the stream recorded for it. That agreement checks the table against the
CLI, not against the published price page. The prefix identity held at every request of every
context, so the carrying costs below are read counts, not estimates.

Rebuilding the missing final requests worked the same way in both plugin sessions. In `feature-C-1`
each subagent ran on its own model, so the model's residual is that agent's final request. The
prefix identity's prediction of its cache read agreed with the residual for both agents (the
`reconstruction:` lines, `(agrees)`). In the pilot both subagents ran on one model, so their final
requests' cache reads come from the identity. How the residual write splits between them is an
estimate, and the line says so.

What stays an estimate is printed with each table:

- output tokens are apportioned to requests by emitted bytes, within a pool whose total is measured;
- in the content view, a write that held several sources is split by bytes (the tool prints how
  many writes needed it);
- emitted bytes cannot see thinking, whose text is mostly absent from the stream, so a request that
  mostly thought is understated within its pool.

### 1.2 What the pilot's published stage table could not see

`pipeline-pilot.md`'s table apportioned each model's cost across stages by input-side weights. The
stream lacks the subagents' final requests, so those were missing from the weights. The billing view
here prices each request directly. Both columns describe the same session (`<p>`):

| Stage | Published, apportioned (`pipeline-pilot.md` §4) | Billed (`stream-cost.py <p>/stream.jsonl`, `per stage, as billed`) |
|---|---|---|
| main, up to the executor dispatch | `0.7735` | orient `0.1036` + plan `0.6886` |
| executor | `0.0738` | `0.0715` |
| gate | `0.1467` | `0.1562` |
| reviewer | `0.0572` | `0.0595` |
| close | `0.2365` | `0.2085` |

The published reading holds: the main loop up to the dispatch was the largest share either way.
The differences have two causes. The published split attributed output in proportion to input
share, whereas output is now measured per pool. And its weights inside one model lacked each
subagent's final request.

## 2. Observation 1 — why the main loop before dispatch was the largest share

`python3 tools/stream-cost.py <p>/stream.jsonl` — billing view, then content view:

```
per stage, as billed
  stage       req    in cacheW5m cacheW1h    cacheR     out   $cacheW  $cacheR     $out   $total  share
  orient        2     4        0    10740     31679     564    0.0859   0.0063   0.0113   0.1036   8.0%
  plan          7    14        0    63562    511821    3886    0.5085   0.1024   0.0777   0.6886  53.5%
  executor     4*     8    18809        0     50375    1434    0.0470   0.0101   0.0143   0.0715   5.5%
  gate          3     6        0     6104    262931    2736    0.0488   0.0526   0.0547   0.1562  12.1%
  reviewer     2*     4    16147        0     14865    1614    0.0404   0.0030   0.0161   0.0595   4.6%
  close         5    10        0     7306    474452    2754    0.0584   0.0949   0.0551   0.2085  16.2%

per stage, by what it put there
  stage          $run    $task    $file   $total  share
  orient       0.7916   0.0000   0.0000   0.7916  61.5%
  plan         0.0000   0.1456   0.0074   0.1530  11.9%
  executor     0.0000   0.0768   0.0043   0.0811   6.3%
  gate         0.0000   0.0976   0.0000   0.0976   7.6%
  reviewer     0.0000   0.0697   0.0030   0.0727   5.6%
  close        0.0000   0.0917   0.0000   0.0917   7.1%

largest cache writes
  stage     class  tokens   bytes  B/tok reads   $write   $carry   $total  source
  orient    run     21933   60601   2.76    14   0.1755   0.0614   0.2369  Read <plugin>/reference/orchestrator.md
  orient    run     21895   60495   2.76    14   0.1752   0.0613   0.2365  Read <plugin>/reference/execute-task.md
  executor  task    16131       0      -     3   0.0403   0.0097   0.0500  agent start: audit:audit-executor
  reviewer  task    14865       0      -     1   0.0372   0.0030   0.0401  agent start: audit:audit-reviewer
  orient    run     13641   37690   2.76    14   0.1091   0.0382   0.1473  Read <plugin>/reference/manifest-conventions.md
  orient    run     10049       0      -    16   0.0804   0.0322   0.1125  session start
```

What the main loop did before the dispatch, in numbers:

- **It read the prose `commands/run.md` names up front, in its orient requests.** The reference
  files arrived as `Read` results. They entered the cache with the next request, and the main loop
  writes at the one-hour rate. The `Read` rows above came to 57469 tokens and `$0.4598` written
  (derived: 21933 + 21895 + 13641 tokens; 0.1755 + 0.1752 + 0.1091 USD).
- **Every later main-loop request re-read them.** Each `Read` row shows reads of 14, and that
  carrying came to `$0.1609` (derived: 0.0614 + 0.0613 + 0.0382).
- **The billing view puts that write on `plan`'s first request,** the request whose context the
  prose entered. This is why billed `plan` reads 53.5% while `plan`'s own content reads 11.9%: the
  manifest work itself (preflight, lock, task start, the brief) cost `$0.1530` in the content view.
- **Read by content, `orient` is the run class.** At `$0.7916` it is the session's start, plus the
  plugin's prose, plus every later read of both. Some of that is paid by gate and close requests,
  which re-read it. That figure is 61.5% of the pilot.

So the observation is explained by one thing. Before any work, the main loop reads the reference
prose its command names: about 57k tokens, measured as cache writes. It then carries that prose on
every request it makes afterwards. The manifest work it does in the same stretch is a small part of
the bill.

## 3. Observation 2 — why the plugin arm cost several times the plain arm

The totals, as `stream-cost.py` prices them (`all models priced=`): `feature-C-1` `1.748411`,
`feature-A-1` `0.284359`, `feature-A-2` `0.311679`, which is 6.1 and 5.6 times (derived). By content
class (`by content class`, the `$total` column):

| Class | `feature-C-1` (plugin) | `feature-A-1` (plain) | `feature-A-2` (plain) |
|---|---|---|---|
| run — fixed per run | `0.7532` | `0.0598` | `0.0593` |
| task — per task | `0.7742` | `0.0192` | `0.0677` |
| file — per file the work touches | `0.2211` | `0.2054` | `0.1847` |

Read off the table:

- **The work itself cost about the same in both arms.** Reading the `shop` package and writing the
  coupon feature and its tests is the file class, which cost about the same whether the main loop
  did it (plain) or an executor did it (plugin).
- **The difference is the run and task classes.** Against `feature-A-1`, run adds `0.6934`, task
  adds `0.7550` and file adds `0.0157` (derived: the column differences).

What the run class holds in `feature-C-1`
(`python3 tools/stream-cost.py <x>/feature-C-1/stream.jsonl`, `largest cache writes`):

```
  stage     class  tokens   bytes  B/tok reads   $write   $carry   $total  source
  orient    run     21913   60601   2.77    12   0.1753   0.0526   0.2279  Read <plugin>/reference/orchestrator.md
  orient    run     21875   60495   2.77    12   0.1750   0.0525   0.2275  Read <plugin>/reference/execute-task.md
  executor  task    16952       0      -     8   0.0848   0.0271   0.1119  agent start: audit:audit-executor
  reviewer  task    15878       0      -     3   0.0397   0.0095   0.0492  agent start: audit:audit-reviewer
  orient    run     13629   37690   2.77    12   0.1090   0.0327   0.1417  Read <plugin>/reference/manifest-conventions.md
  orient    run      9304       0      -    14   0.0744   0.0261   0.1005  session start
```

The reference reads alone came to `$0.5971` (derived: 0.2279 + 0.2275 + 0.1417), more than either
plain session's whole cost. The session start was bigger too: the plugin session wrote
9304 tokens on its first request against 5000 for `feature-A-2` (the `session start` rows). Both
sessions found the same 11891-token prefix already cached (the `contexts:` section, `start_cR`).
That difference covers the plugin's listing, `run.md`'s body and arm B's skills and rules, which C
carries because C is B plus the plugin. B was not run, so these records cannot split it further.

What the task class holds, by stage
(`per stage, by what it put there`, `$task`, for `<x>/feature-C-1`): plan `0.1526`, executor
`0.2341`, gate `0.1261`, reviewer `0.0873`, close `0.1740`. It is made of:

- **Each agent's start is written fresh at every dispatch.** Both agents' first requests found
  nothing cached (`contexts:`, `start_cR` 0). They wrote 16952 tokens (executor) and 15878
  (reviewer) before reading a line of the project.
- **The main loop types a lot.** Its measured output was 14031 tokens, from the
  `output pool, measured: main loop` line, against 6593 for the whole of `feature-A-1` (the same
  line in its report). The main loop's largest items were the briefs it wrote for the agents, and a
  brief is output, the dearest token in the table (`largest outputs`):

  ```
  executor     4081   0.0816  Write <repo>/tests/test_coupons.py (7878 B); Bash python3 -m unittest …
  executor     3125   0.0625  hand-back text (6142 B)
  plan         2840   0.0568  brief for audit:audit-executor (5211 B); text and thinking (109 B)
  gate         2817   0.0563  brief for audit:audit-reviewer (4935 B); text and thinking (341 B)
  ```

- **Hand-backs and the plugin scripts' output** enter the main loop's context and are carried by
  every request after them.

Time follows the same shape. In the plugin session the executor took 82.2s alone
(`per stage, as billed`, `wall_s`), longer than either plain session's whole stream (50.8s and
55.8s, the same column in their reports).

## 4. Fixed per run, per task, per file

From `feature-C-1`, the one plugin session that did a feature
(`python3 tools/stream-cost.py <x>/feature-C-1/stream.jsonl`):

| Part | What it is | Figure |
|---|---|---|
| fixed per run, written once | the session start, plus the reference prose the command reads first | run `$write` `0.5406` (`by content class`) |
| fixed per run, carried per main-loop request | the same tokens, re-read by every later main-loop request | run `$carry` `0.2017`; a further main-loop request re-reads 79461 run-class tokens (`contexts:`, `run`) |
| per task | the agent starts, briefs, hand-backs, plan and gate output, the model's own text | task `$total` `0.7742` |
| per file | project files read and code written | file `$total` `0.2211` |

**The fixed part is not fixed in a run of several tasks.** That is inference, from how the identity
works. It is written once, but every main-loop request re-reads it. At C-1's end that was 79461
run-class tokens, `$0.0159` per request at the shipped cache-read rate (derived: 79461 × 0.20 / 10^6).
The main loop's requests after orient wrote the prose, then re-read it: the `reads` column of each
reference row counts the re-reads, and the run `$carry` above prices them together with the
re-reads of the session start. Those requests are the pipeline's per-task steps: start, dispatch,
gate, review dispatch, commit, done. A run of several tasks therefore pays the prose again on every
task's steps, on a prefix that grows with each hand-back. A single-task recording cannot measure
how many main-loop requests a second task adds, or which of C-1's are paid once per run (the lock,
the preflight).

## 5. What the prompt cache saves, and what it cannot

`python3 tools/stream-cost.py <record>/stream.jsonl`; the block is condensed from each report's
`cache [...]` lines. "Without the cache" prices the same tokens with every input-side token at the
base input rate.

```
              without   billed    saved   reads paid  write premium  (never re-read)  output
feature-C-1    6.4601   1.7484   4.7117     0.2764        0.4161          0.0146       0.5075
pilot          5.9042   1.2878   4.6165     0.2692        0.3683          0.0115       0.2293
feature-A-1    0.4969   0.2844   0.2126     0.0148        0.0688          0.0265       0.1319
feature-A-2    0.7154   0.3117   0.4037     0.0249        0.0702          0.0238       0.1464
```

**What it saves.** In `feature-C-1` the cache cut the input side by `$4.7117` (`saved`). Without
it, re-reading the reference prose on every request would have been priced like reading it fresh,
every time.

**What it cannot save:**

- **The first write.** Every token enters at the write rate, which is above base input. The main
  loop writes at the one-hour rate, the subagents at the five-minute rate (the `cacheW1h` and
  `cacheW5m` columns of `per stage, as billed`). For `claude-opus-5-5` the shipped table prices
  those at twice and one and a quarter times base input. The `write premium` column is what that
  surcharge cost. The plain sessions' main loops also wrote at the one-hour rate, so this belongs
  to the CLI, not to the plugin. Repricing C-1's main-loop writes at the five-minute rate instead
  gives `$0.2791` less. That is derived from the `cacheW1h` column over orient, plan, gate and
  close (9922 + 63456 + 7846 + 11801 = 93025 tokens), times the difference between the table's
  rates for the two TTLs (8.0 − 5.0 per million).
  Whether that rate is a choice open to a pipeline, and whether the gaps in a longer run stay
  inside five minutes, is not measured here.
- **The re-reading itself.** Every request still pays for its whole prefix at the read rate: the
  `reads paid` column. One more main-loop request cost `$0.0210` at the end of `feature-C-1`
  (`contexts:`, `$/request`).
- **A new context.** A subagent shares nothing with the main loop's cache. Both agents' first
  requests read nothing from cache (`start_cR` 0), so their starts are written in full on every
  dispatch.
- **Output.** It is never cached, and in the plugin session it was the largest single price type
  after cache writes (the `output` column).

## 6. The largest single contributors

**In a run** (`feature-C-1`, from the two lists above): the three reference files the command reads
first (`$0.2279`, `$0.2275`, `$0.1417` with their reads), the executor's start (`$0.1119`), the
session start (`$0.1005`), the executor's test file (`$0.0816` of output; it is file-class work the
plain arm also did), the executor's hand-back (`$0.0625`), the two briefs (`$0.0568`, `$0.0563`)
and the reviewer's start (`$0.0492`).

**In the prose the plugin ships, at the published tag and at `main`.** The command below uses the
calibrated divisor (section 6.1):

```
python3 tools/measure-context.py --ref v3.1.0 --ref main --bytes-per-token 2.63

                             v3.1.0 (b090fbd5109c)        main (a73b836a9e8c)
  listing (always on)          9659 B   ~3673 tok           9659 B   ~3673 tok
  /audit:run                 153938 B  ~58532 tok         159474 B  ~60637 tok
  /audit:next                150516 B  ~57230 tok         155867 B  ~59265 tok
  /audit:phase               235948 B  ~89714 tok         242068 B  ~92041 tok
  sign-off (/audit:review)   144869 B  ~55083 tok         149138 B  ~56706 tok
  executor                    16003 B   ~6085 tok          18790 B   ~7144 tok
  reviewer                    15689 B   ~5965 tok          15689 B   ~5965 tok

largest contributors, each file once [bytes]:
  file                                     v3.1.0         main     delta  loaded by
  reference/orchestrator.md                 55898        59104     +3206  /audit:run, /audit:next, /audit:phase, sign-off (/audit:review)
  reference/execute-task.md                 56806        58657     +1851  /audit:run, /audit:next, /audit:phase
  reference/phase-signoff.md                47841        48598      +757  /audit:phase, sign-off (/audit:review)
  commands/phase.md                         39769        39769        +0  /audit:phase
  reference/manifest-conventions.md         35634        35940      +306  /audit:run, /audit:next, /audit:phase, sign-off (/audit:review)
  agents/audit-executor.md                  16003        18790     +2787  executor
  agents/audit-reviewer.md                  15689        15689        +0  reviewer
```

The per-entry totals above are condensed from the command's own per-entry `total` lines. Between the
tag and `main` the prose grew. Nothing loaded shrank by more than a few bytes, and the delta column
names the files that grew. `orchestrator.md` and `manifest-conventions.md` load on every pipeline
command that runs work. `/audit:phase` loads the most, because it reads both the task half and the
sign-off half before it starts.

In a project with a large `CLAUDE.md`, the agents' column changes most: subagents load the project's
`CLAUDE.md`. In this repository, where the plugin is used on itself, that file was larger than
either agent's own prompt on 2026-10-07:
`python3 tools/measure-context.py --ref main --claude-md CLAUDE.md --bytes-per-token 2.63`.

### 6.1 The divisor, calibrated

The files `/audit:run` reads first held 151022 bytes at the commit `feature-C-1` ran. That is
derived from the `read first` rows of `python3 tools/measure-context.py --ref 5df231ec76c9`:
57593 + 35634 + 57795. The pilot's commit `b6d9a4a31d2a` gives the same sizes. As cache writes they
came to 57417 tokens in `feature-C-1` and 57469 in the pilot, derived by summing the
`Read <plugin>/reference/…` rows of each session's `largest cache writes`. That works out to 2.63 bytes per token of file (derived: 151022 / 57417),
with line numbers as the `Read` tool adds them. The tool's default of 4 is the conventional
English-prose rule. On this prose it understates by about a third (derived: 1 − 2.63 / 4), so a
prediction about the reference files should pass `--bytes-per-token 2.63`. The two sessions read
identical files, so their agreement shows the count is stable for this prose. It says nothing about
prose written differently.

## 7. Limits

- **One session per cell.** One pilot, one plugin-arm benchmark session and two plain sessions, each
  measured once.
- **Single-task runs only.** What a second task adds is inference (section 4), not measurement. The
  stage rule for a run of several tasks counts the next task's plan work in the previous task's
  close; no session here exercised that.
- **Arm B was not run.** The run class's session start mixes the plugin's listing with arm B's
  skills and rules. The reference prose is the plugin's alone: its own command reads it.
- **Estimates are labelled where they are printed:** output apportioned by emitted bytes inside a
  measured pool (thinking mostly unseen), the size split inside a write that held several sources,
  and the pilot's two final requests on one model.
- **The content classes follow rules,** which the tool's docstring states. A tool call is classed by
  its tool, its path and, for a shell command, whether every segment only looks at files. A command
  that both views and runs counts as task work.
- **Prices are the plugin's shipped table.** It reproduced every `costUSD` exactly, which checks it
  against the CLI, not against the published page.

## 8. Re-deriving every figure

| Figure | Command |
|---|---|
| per-stage billing, content view, classes, cache economics, largest writes and outputs, contexts | `python3 tools/stream-cost.py <record>/stream.jsonl` (`--json` for every row) |
| the prose each pipeline step loads, and its growth between refs | `python3 tools/measure-context.py --ref v3.1.0 --ref main --bytes-per-token 2.63` |
| the sizes at the commits the sessions ran | `python3 tools/measure-context.py --ref 5df231ec76c9 --ref b6d9a4a31d2a` |
| the tools' own proof | `python3 tools/stream-cost.py --selftest`, `python3 tools/measure-context.py --selftest` |
| the published figures compared in section 1.2 | [pipeline-pilot.md](pipeline-pilot.md) §4, [benchmark-results.md](benchmark-results.md) §2.4 |
