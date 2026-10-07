# Pipeline pilot — one paid `/audit:run` on the bench fixture

One `claude -p "/audit:run P1.1"` was run on 2026-10-06 against the bench fixture, to see what a
task costs and where the pipeline stalls when the plugin's own commands drive it end to end. This
document reports that run. **It is one run, measured once**: every figure below is a reading of
that run, not a property of the pipeline, and nothing here says whether the plugin helps — that is
the with/without comparison's question, under `benchmark-design.md`.

The findings in section 6 are the input the phase that moves prose rules into scripts waits on.

## 1. What was run

| | |
|---|---|
| Plugin under test | `plugins/audit` exported with `git archive` at local `main` `b6d9a4a31d2a`, `plugin.json` 3.1.0 (`<export-meta.json>`) |
| Fixture | the probe's bench repository (one seeded pricing bug, one failing test), built fresh with `build_bench_repo.sh plugin` and the probe's `bench-manifest.json` |
| Command | `/audit:run P1.1` as the whole prompt |
| Model, effort | `claude-opus-5-5`, `medium` — the probe's pins, unchanged |
| Cap | `--max-budget-usd 4.50`, against a 5 USD allotment; `--max-turns 30` |
| Permissions | `--permission-mode acceptEdits --permission-prompts none`, `--setting-sources project,local`, `--strict-mcp-config`, the rendered arm file as `--settings` |
| Claude Code | 2.1.291 (`<run-meta.txt>`) |

The harness is the internal benchmark harness, `reports/2026-10-05-deep-analysis/fixtures/bench/`
in the internal repository. The pilot used a copy of it; what changed from the probe's copy:

- `export_plugin.sh` re-pinned from `b090fbd5` to the commit under test;
- `prompt.txt` holds the command, and `run_bench.sh` refuses to launch on anything else;
- `run_bench.sh` and `build_bench_repo.sh` build the plugin arm only, render the arm file against
  the run's own export and fixture (`render_arm.py`), drop every `CLAUDE*`/`AUDIT_*` variable of the
  calling session except the account selectors, and refuse a second paid launch;
- `extract_metrics.py`, `quality_check.py` and the probe's plugin arm file are byte-identical to
  the probe's (`cmp original/<file> harness/<file>`, exit 0 for each).

The run's artifacts — `<stream.jsonl>`, `<metrics.txt>`, `<quality.txt>`,
`<settings-snapshot.json>`, `<arm-added-rules.tsv>`, `<plugin-reference-bytes.txt>`,
`<run-meta.txt>`, `<export-meta.json>`, `<diff.patch>`, `<git-log-all.txt>`, and the stage
splitter `<split script>` — are kept in the internal repository's analysis folder. This document
names them by those placeholders and no machine path.

## 2. Headline

`python3 extract_metrics.py <stream.jsonl>` (`<metrics.txt>`):

```
result   subtype=success error=False terminal=completed turns=19 duration_ms=131855 api_ms=124266
cost     total_cost_usd=1.2877505999999994 (list-price equivalent on a subscription)
tokens   claude-opus-5-5 in=34 cache_write=87712 cache_read=1280883 out=9940 costUSD=1.1568085999999997
tokens   claude-sonnet-5-5 in=12 cache_write=34956 cache_read=65240 out=3048 costUSD=0.130942
denials  0
requests main=17 subagent=4  tools=Agent:2,Bash:15,Edit:2,Read:4
check    modelUsage vs per-message sums (input side): DISAGREE {...}; output gap +12033
         (stream carries emit-time output counts - quote modelUsage)
```

`python3 quality_check.py <fixture repo> <stream.jsonl>` (`<quality.txt>`):

```
Q1_tests_pass        True
Q2_bug_fixed         True
Q3_tests_untouched   True
Q4_scope_ok          True
Q5_claims            True
VERDICT              PASS
```

The cost is the list-price equivalent the session reports (`total_cost_usd`, `costBasis: list` in
`modelUsage`); the run was on a subscription, so it is not a bill. The cap was never approached.

The run ended with the task closed and its work committed (`b005277`, on
`audit/p1-pricing-correctness`), the phase still `in_progress` with sign-off due, and the manifest
and journal modified but uncommitted (`<git-status.txt>`, `<git-log-all.txt>`). That is where
`/audit:run` is specified to stop — it never signs a phase off — so it is not a stall.

## 3. What the orchestrator prose drove

The main loop read its reference files in full with `Read` before its first action, after a
`wc -l` of the same files. The bytes each `Read` returned (line-numbered text, so larger than the
file) come from `python3 <split script> <stream.jsonl>`:

```
reference files the main loop Read [stream, bytes of the tool_result text]:
  main      reference/orchestrator.md              60601
  main      reference/execute-task.md              60495
  main      reference/manifest-conventions.md      37690
  executor  shop/pricing.py                          822
```

The files' own sizes in the export, `wc -c` (`<plugin-reference-bytes.txt>`):

```
    5887 commands/run.md                 the prompt the command expands to
   57795 reference/execute-task.md       Read by the main loop
   35634 reference/manifest-conventions.md   Read by the main loop
   57593 reference/orchestrator.md       Read by the main loop
   17005 agents/audit-executor.md        the executor's system prompt
   16221 agents/audit-reviewer.md        the reviewer's system prompt
```

`reference/phase-signoff.md` was not read, as `run.md` says, and neither was
`reference/tracker-sync.md`. No skill was invoked (`skills=-` on `<metrics.txt>`'s `tests` line).

## 4. Cost, tokens, turns and time per stage

`extract_metrics.py` splits main loop from subagent only, so the split below is a separate script,
kept with the artifacts. Stages are cut at the two `Agent` calls: **main** is the main loop up to
and including the executor dispatch; **executor** and **reviewer** are the events whose
`parent_tool_use_id` is that subagent's call; **gate** is the main loop from the executor's
return up to and including the reviewer dispatch (the recorded gate and the stamp grading);
**close** is the main loop after the reviewer returned (commit, `done`, lock release, the final
message).

`python3 <split script> <stream.jsonl>`:

```
[modelUsage] per model (the result event):
  claude-opus-5-5      in=34 cacheWrite=87712 cacheRead=1280883 out=9940 costUSD=1.1568
  claude-sonnet-5-5    in=12 cacheWrite=34956 cacheRead=65240 out=3048 costUSD=0.1309
  total_cost_usd=1.2878  duration_ms=131855  num_turns=19  permission_denials=0

per stage: requests [stream], input-side tokens [stream], wall clock [stream timestamps], cost [apportioned]
  stage     model              req     in   cacheW    cacheR   wall_s  cost_usd  tools
  main      claude-opus-5-5      9     18    74302    543500     49.6    0.7735  Agent:1,Bash:6,Edit:1,Read:3
  executor  claude-sonnet-5-5    3      6    17533     32842     16.1    0.0738  Bash:2,Edit:1,Read:1
  gate      claude-opus-5-5      3      6     6104    262931     24.1    0.1467  Agent:1,Bash:2
  reviewer  claude-sonnet-5-5    1      2    14865         0     12.0    0.0572  Bash:1
  close     claude-opus-5-5      5     10     7306    474452     28.3    0.2365  Bash:4
  sum                           21                              130.0    1.2878
  first-to-last stream timestamp only; the result's duration_ms also covers the time to the first one

subagent hand-backs [stream, the Agent tool_result's own <usage> block]:
  audit:audit-executor   tokens=19573 tool_uses=4 duration_ms=16017
  audit:audit-reviewer   tokens=17369 tool_uses=1 duration_ms=11920
```

Which source each figure comes from, as the script labels it:

- **modelUsage** — the per-model totals and `total_cost_usd` in the result event. The only output
  counts and the only cost figures that are measured rather than derived.
- **stream** — per-request usage, de-duplicated by `message.id`. Its request count matches
  `extract_metrics.py`'s main/subagent split. Its output counts are emit-time and undercount, as
  `<metrics.txt>`'s `check` line says, so the script prints none; its input-side sums also differ
  from `modelUsage` by the amounts that line names.
- **apportioned** — each model's `costUSD` split across the stages that used it, in proportion to
  input-side tokens weighted 1 : 2 : 0.1 (input, one-hour cache write, cache read — the published
  multipliers). Because every stage runs on one model, executor plus reviewer is exactly the
  Sonnet `costUSD`, and main plus gate plus close exactly the Opus one. The split *within* a model
  is an estimate: output cost cannot be attributed from the stream, so it rides along with input
  share, and an output-heavy stage — close, which writes the final message — is understated.
- **turns** — the run reports `num_turns` once, for the whole session; per stage the script counts
  API requests instead.

Read off the table: the largest apportioned share of the spend and the longest stretch of wall
clock fall in **main**, before any work is dispatched, and its cache write is where the reference
files land in context. The subagents together cost less than the gate stage's apportioned share.

## 5. Permissions: the arm and what it actually covered

The probe's arm file allowed only the test command and read-only git. The pilot's arm had to add
the plugin's own script calls and the git verbs the pipeline needs. Every rule added, as
`render_arm.py` printed it (`<arm-added-rules.tsv>`; `cut -f1 <arm-added-rules.tsv> | sort | uniq -c`
counts them by kind), with the export's root written `<plugin>` and the fixture's `<repo>`:

| Kind | Rule |
|---|---|
| allow | `Bash(python3 "<plugin>/scripts/governance/audit-lock.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/manifest/validate-manifest.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/status/audit-status.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/manifest/resolve-branch.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/manifest/audit-task.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/status/audit-lookup.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/governance/run-test-gate.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/governance/stamp-verification.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/governance/commit-task-work.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/governance/commit-manifest-index.py" *)` and the unquoted spelling |
| allow | `Bash(python3 "<plugin>/scripts/governance/commit-audit-state.py" *)` and the unquoted spelling |
| allow | `Bash(git rev-parse *)`, `Bash(git add *)`, `Bash(git commit *)`, `Bash(git checkout -b *)`, `Bash(git switch *)`, `Bash(git worktree *)`, `Bash(git merge *)` |
| allow | the same verbs as `git -C . <verb> *`, plus `git -C . status *`, `git -C . diff *`, `git -C . log *` |
| allow | the same verbs again as `git -C <repo> <verb> *` |
| deny | `Bash(git add -A *)`, `Bash(git add --all *)`, `Bash(git add . *)`, `Bash(git add -u *)`, `Bash(git add --update *)`, `Bash(git commit -a*)`, `Bash(git commit --all *)` |
| deny | the same denials under `git -C . ` and under `git -C <repo> ` |

What the run actually leaned on is the other half of the answer.
`python3 <split script> <stream.jsonl> <settings-snapshot.json>` matches every Bash segment
(split on `;`, `&&`, `||`, `|` and newline outside quotes) against the allow rules, prefix before
the `*` — an approximation of the harness's matcher, printed per segment. Its reading:

- **Every plugin-script call the main loop made matched no rule.** The main loop wrote each one as
  `cd <repo>; PR=<plugin>; python3 "$PR/scripts/…"`, and no rule names `$PR`. None was denied
  (`permission_denials` is empty in the result event).
- **Added rules exercised**: the executor's `stamp-verification.py take`, which spelled the plugin
  path out in full, and the main loop's `git rev-parse --show-toplevel`. The rest of what matched —
  the test command, `git diff`, `git log`, `git status` — was already in the probe's arm.
- The reviewer's `cat` and `ls`, and the main loop's `ls`, `find`, `cat` and `echo`, matched no rule
  and were not denied either.

## 6. Where it stalled — the predicted points and what else happened

The preparation predicted stall points before the run. Each is graded against the stream.

**The executor's stamp goes stale only because the gate's `--record` writes the evidence ledger —
happened.** The executor took its stamp at 21:49:49; the only command between that and the main
loop's `stamp-verification.py compare` at 21:50:09 that wrote anything was
`run-test-gate.py … --record` (beside it ran only `git diff`), and the
evidence ledger it wrote is one of the files `commit-task-work.py` later committed. The compare
returned `VERDICT: stale` with `head`, `scopeDigest` and `content` agreeing and only `dirtyDigest`
— which paths were dirty — moved; exit 1. The main loop did not re-take anything; it cited the
recorded gate run instead, wrote that into the task's outcome, and said so in its final message.
The verdict is correct by its own definition and still told the orchestrator nothing about the
declared work: the pipeline's own recording step invalidates the stamp it is about to grade.

**A `done` note with `>` on argv stalls — did not happen.** The close stage's
`audit-task.py done … --technical "…'subtotal > threshold' changed to 'subtotal >= threshold'…"`
exited 0 (`done=0`, `validate=0` printed after it), and no hook returned any output on that call;
the only hook output in the whole stream is the TDD reminder below.

**`run.md`'s `allowed-tools` pre-approves `Bash` and `Read` for the main loop — happened, by
inference.** `commands/run.md`'s front matter lists `allowed-tools: Read, Edit, Bash, Agent, Skill,
Glob, Grep, AskUserQuestion`. Section 5 shows every main-loop plugin-script call outside every arm
rule and none denied under `--permission-prompts none`; the frontmatter grant is the explanation
consistent with both. The stream does not record why a call was allowed, so this is an inference
from rule text and the empty denial list, not an observation. Its consequence is the one that
matters: the arm file's added rules constrained the subagents and not the orchestrator, so this
run says nothing about whether those rules are sufficient for the main loop.

What else the stream shows, none of which stopped the run:

- **The main loop hand-edited the manifest.** Phase entry — `P1` to `in_progress` — was an `Edit`
  of `docs/audit/audit-plan.json`, not a script verb; `audit-task.py start` then rewrote the file
  and reflowed its JSON.
- **The main loop guessed argv twice.** It ran `audit-task.py start P1.1 <manifest> || audit-task.py
  start P1.1`, and in close ran `audit-task.py done --help` before calling `done` — one extra
  request to learn flags the prose did not hand it.
- **The executor read the test exit code through a pipe** (`… 2>&1 | tail -5; echo exit=$?`). It
  said so itself in its hand-back; the main loop's recorded gate supplied the real exit code.
- **The TDD reminder fired against the task.** After the executor's edit of `shop/pricing.py`, the
  PostToolUse hook told it that in `regression` mode the order is implement then add tests, and
  that "Adding none is what this is reminding you about" — on a task whose description says not
  to change the tests. The executor correctly ignored it.
- **The plugin's own usage line disagrees with the session.** `audit-status.py --short` at the end
  printed `usage: 995.7K tok - ~$1.56 equiv - rates undated`, against the session's
  `total_cost_usd` above. The two count different things — the plugin's ledger and its own rate
  table against the session's `modelUsage` — and this run does not reconcile them.

## 7. Re-deriving every figure

| Figure | Command |
|---|---|
| headline, per-model tokens and cost, denials, requests | `python3 extract_metrics.py <stream.jsonl>` |
| quality verdict | `python3 quality_check.py <fixture repo> <stream.jsonl>` |
| per-stage split, subagent hand-backs, reference bytes read | `python3 <split script> <stream.jsonl>` |
| which Bash calls an arm rule covered | `python3 <split script> <stream.jsonl> <settings-snapshot.json>` |
| reference file sizes | `wc -c commands/run.md reference/*.md agents/*.md` in the export (`<plugin-reference-bytes.txt>`) |
| rules the arm added | `<arm-added-rules.tsv>`, as `render_arm.py` printed it |
| plugin commit under test | `<export-meta.json>` |
