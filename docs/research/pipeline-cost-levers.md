# Pipeline cost — the rest, located per step, and the levers that cut it

This follows [pipeline-cost-results.md](pipeline-cost-results.md). That document read the
implemented phase against the cost target. This one locates the cost that is left, one step at a
time, in the same recorded sessions, and designs the levers the next phase builds. Each lever names
its mechanism, the guarantee it keeps, and the offline micro-test that must pass before any paid
session. No model call was made to write it.

**Every session was run once.** Each figure from a session is one observation of that session. None
is a rate.

**What the sessions show**, each line carrying the section that holds its readings:

- **The phase overhead, per step** (section 2). Planning is where the sessions differ. A write the
  session could not make cost `cost-C-2` `0.1562` and `cost-C-3` `0.5068`, and `cost-C-1`, whose
  write went through, nothing. The plugin's own sign-off steps cost about the same in every session:
  the review dispatch `0.1560` to `0.1652`, the triage `0.0168` to `0.0218`, and the answer that
  runs the phase gate, the invariants, the sign-off verb, the commit, the landing and the lock
  release `0.0199` to `0.0374`. That answer's script work is one driver call of 2.4 to 2.6 seconds;
  its cost is the main-loop request around it.
- **The phase review's value test** (section 3). In each session it filed no finding, answered
  `matches` for every task, and nothing outside the plan changed between the head it reviewed and
  the landed tree. So no graded result and nothing shipped moved because of it. The driver's
  computed signal would have called more reviews here, not fewer, and a phase-level one would have
  skipped one review in three.
- **The executor's hand-back** (section 4). It costs `0.0504`, `0.0593` and `0.0557` of each cycle
  and `0.0030` to `0.0039` after it. The results document's estimate of what one line would leave
  missed a part the main loop receives whatever the agent writes: the CLI's frame and trailer. With
  it, one line takes the cycles to 1.254, 1.333 and 1.189 like for like.
- **`CLAUDE.md` in each agent's start** (section 5). It is 2193 bytes, an estimated 548 to 834
  tokens. No brief restated every rule in it, and none restated the rule the grader checks. Leaving
  it out would save an estimated `0.0039` to `0.0103` a cycle and would drop those rules. It is not
  recommended.
- **The levers** (section 6). Four are recommended: the plan batch on stdin, the hand-back line
  printed where the agent last reads, sign-off answered in advance, and the review's mechanical
  answers computed. Predicted, the phase overhead reads `0.5653`, `0.5501` and `0.7096`, under its
  1.00 budget in every session and under each estimate taken the adverse way. The per-task ratio
  moves toward the 1.25 ideal and reaches it in `cost-C-3` only.
- **The instrument** (section 1). `tools/stream-cost.py` now reads the streams of one resumed
  session in one call, and refuses a follow-up stream read alone rather than mispricing it.

## 0. How to read this

The labels **measured**, **derived**, **estimate** and **inference** mean what the results
document's section 0 says. So do the paths. `<analysis>` is the internal repository's analysis
folder, `reports/2026-10-05-deep-analysis/`. `<x3>` is `<analysis>/experiments/bench-feature-cost`,
`<xp>` is `<analysis>/experiments/bench-feature-cost-probe`, and `<fixture>` is the repository a
session ran in, which `<x3>/<label>/run-meta.json` → `cwd` names. `<scratch>` is any directory
outside both repositories. Commands run from this repository's root, and section 8 holds every one.

**The pin.** Every `stream-cost.py` figure here was read with the tool as this document's commit
leaves it. Its report on every recorded stream but one is byte-identical to the report of the commit
before it (the corpus command). The one is `cost-C-3`'s follow-up read alone, which it now refuses
(section 1). The prompts and scripts the sessions ran are read at `1dd702f2` with `git show`.

**Prices** are the plugin's shipped table, `_usage_core.DEFAULT_PRICING`. The rates used in the
arithmetic below, per token: Opus writes at `8.0e-6` for one hour and `5.0e-6` for five minutes,
reads at `0.2e-6`, and emits at `20e-6`; Sonnet writes at `2.5e-6` for five minutes, reads at
`0.2e-6`, and emits at `10e-6`. Every main-loop write in these sessions was at the one-hour rate
(the results document's section 6).

**The like-for-like reference** is arm A's mean less its open and close, `0.422075`, and the ideal
is 1.25 times it, `0.5276` of cycle cost (the results document's section 2.1). "÷ A" divides by arm
A's whole mean, `0.504523`.

## 1. The instrument: a follow-up stream read alone

`cost-C-3` took the protocol's scripted follow-up, so it is recorded as two streams. Read alone, the
second printed `claude-opus-5-5 priced=1.227278 costUSD=1.281521 DIFFER by -0.054243` (the results
document's section 6). The difference is derived exactly: `18081 × (8.0 − 5.0) / 10^6 = 0.054243`.
The 18081 is the first stretch's main-loop write, one-hour, in the first stream's result `usage`. A
resumed stream's result carries the whole session's `modelUsage`, so that write arrived with no
request to hold it. The tool put it in the rebuilt final request of the follow-up's one Opus
dispatch, at that dispatch's five-minute rate. The same final absorbed the first stretch's whole
cache read, 104007 tokens.

**What the tool does now.**

- **Several streams in one call.** `python3 tools/stream-cost.py <first> <follow-up>` reads them as
  one session, in the order named. Each stream must name one session in its `init` event, and each
  must begin after the one before it ends; otherwise the call exits 2 and names the stream at fault.
  On `cost-C-3` it prints, byte for byte, what the two files concatenated into one print, as text
  and with `--json` (the corpus command's `cmp` lines).
- **A follow-up read alone is refused.** The check is `unheld_reads()`. A final request reads at
  most its context's last read plus write; that is the prefix identity. So `modelUsage` cache reads
  above every request the stream shows, plus that bound for each unseen final, belong to no request
  in the stream. A positive excess on any model exits 2, names the model and the tokens, and says to
  name every stream of the session. A shortfall is an identity break, which the content view already
  reports, so it is not counted. Writes cannot tell the two cases apart, because a final's write is
  whatever its tail was.

**Measured over every recorded stream** (the corpus command): the refusal fires on one, `cost-C-3`'s
follow-up read alone, naming `claude-opus-5-5: 104007 tokens`. Every other stream exits 0 with the
report it printed before. That is the reading the check rests on, and it is one reading of a fixed
set of records.

The selftest cases are `sc30` to `sc34` in the tool. `sc32` is the allow twin. It reads three
sessions normally: a whole one with a rebuilt final on the main model, one re-invoked inside one
stream, and one whose final read falls short of the prefix identity.

## 2. The phase overhead, per step

The step command prices each main-loop request with the agents it dispatched, grouped by what the
request did (the calls command of the results document's section 7 says what each did). The phase
overhead is every step outside the cycle, less the project's own `reviewer` agent, which arm B pays
too. The step command prints that agent apart.

| Step | `cost-C-1` | `cost-C-2` | `cost-C-3` |
|---|---|---|---|
| the session start: the command body and the first answer | 1: `0.0791` | 1: `0.0709` | 1: `0.0716` |
| planning's own reads | 2–3: `0.0775` | 2–3: `0.0371` | 2–4: `0.0842` |
| the question to the human | — | — | 5: `0.0662` |
| the plan typed and added | 4: `0.1171` | 4: `0.1719` | inside the next row |
| a write that failed, and the way round it | — | 5–7: `0.1562` | 6–15: `0.5068` |
| the run form invoked again | — | — | 16: `0.0233` |
| *the cycle* | *5–11: `0.5657`* | *8–14: `0.6084`* | *17–23: `0.5442`* |
| the phase review: its dispatch and the plugin's reviewer | 12: `0.1560` | 15: `0.1645` | 24: `0.1652` |
| the triage | 13: `0.0168` | 16: `0.0214` | 25: `0.0218` |
| the sign-off answer: phase gate, invariants, sign-off verb, commit, landing, lock release | 15: `0.0372` | 17: `0.0199` | 28: `0.0374` |
| the main loop's own checks: a diff read or a suite run | 14: `0.0137` | 18: `0.0194` | 26, 29: `0.0186`, `0.0226` |
| the dispatch of the project's reviewer, its request alone | 16: `0.0335` | 19: `0.0315` | 27: `0.0771` |
| the final report | 17: `0.0694` | 20: `0.0577` | 30: `0.0503` |
| **phase overhead** | **`0.6003`** | **`0.7505`** | **`1.1451`** |
| the project's reviewer agent, apart | `0.1341` | `0.1287` | `0.1302` |

Each figure is measured, a request's billed cost with its agents'. The overhead row is the results
document's, and the step command's own sum less the cycle gives the same figure in each session.
`cost-C-1`'s request 16 also ran the suite.

**The phase gate, the invariants, the landing and the lock are not model steps.** The sign-off
answer runs all of them in one driver call: 2.6, 2.4 and 2.4 seconds, printing 291, 284 and 284
bytes (the call-time command, from the stream's stamps). The triage call took 0.3 seconds in each.
What those steps cost the model is the request that makes the call. In the sign-off answer that
request reads the whole prefix, writes what entered since the request before, and emits the call
with its reason: 289 to 359 output tokens, apportioned by bytes (the results document's
request-table command).

**The probe**, `probe-C-1`, ran one task under `/audit:run` and closed it `deferred`, so it had no
sign-off. Its overhead outside the cycle was the status check, `0.0101`, and the final report,
`0.0285` (the step command).

**What varies, and what does not.** The plugin's three sign-off steps together cost `0.2100`,
`0.2058` and `0.2244`, and the final report `0.0503` to `0.0694` (derived, the step rows summed).
Planning, with `cost-C-3`'s second entry into the run form, cost `0.2737`, `0.4361` and `0.7521`.
The largest part of that spread is one cause: a plan that went through the Write tool and could not
be written. In `cost-C-2` the shared `/tmp` held another session's file. In `cost-C-3` Write was
refused twice in the resumed stretch, and its fallback through flags lost the request and the open
choices (the results document's sections 4 and 5.2). `cost-C-3`'s question to the human is the other
part.

## 3. The phase review's value test

The plugin's phase review is `audit:audit-reviewer` at sign-off. Under `review.perTask: phase` it
answers each task's three questions there, and the sign-off verb refuses until every task has its
answer (`reviewer_due()`'s docstring in `drive-phase.py` at `1dd702f2`). Its readings, from the
return command and the after-review command:

| | `cost-C-1` | `cost-C-2` | `cost-C-3` |
|---|---|---|---|
| verdict, findings | `clean`, none | `clean`, none | `clean`, none |
| each task's intent answer | `matches` | `matches` | `matches` |
| `intent.missing` | none | none | `phase.request`, `phase.openChoices` |
| red-first, per task | `proved`, then `could-not-prove` twice | `could-not-prove` throughout | `could-not-prove` twice, then `proved` |
| inherited tests, per task | `not-asked`: the gate runs the whole project | the same | the same |
| files outside `docs/audit` changed between the reviewed head and the landed `main` | none | none | none |
| a graded result it moved | none: nothing changed after it | none | none |
| cost, dispatch with the agent | `0.1560` | `0.1645` | `0.1652` |

**The project's reviewer**, dispatched by the main loop under its `CLAUDE.md` rule 5, reported no
problem in `cost-C-1` and `cost-C-2` (the reviewer-text command). In `cost-C-3` it named one: an
import line of `tests/test_reports.py` edited beyond the approved change. Nothing was changed after
it in any session (the after-review command), so it moved no graded result either.

**What the review was placed to catch and did not.** The grader flagged `protected_test_modified` in
`cost-C-1` and `cost-C-3` (the results document's section 3). The existing-test command lists, per
session, the test files that existed at the base and that the session modified. It names
`tests/test_reports.py`, the protected file, in exactly those two sessions, and nothing in
`cost-C-2`. In `cost-C-1` the reviewer wrote that the pinned test was untouched, which is true of
the test and not of its file. In `cost-C-3` it called the change user-approved, on the transcript's
word. A computed fact matched the grader's flag where the model's reading did not. That is three
observations, and a file-level fact is not a judgement: appending a test to an existing file is
ordinary work.

**Whether a computed signal would have skipped the review.** The driver already has one, the
`signals` key (`signals_fired` and `reviewer_due` in `drive-phase.py` at `1dd702f2`). It calls a
reviewer for each task whose red-first did not come back `proved`. The return command shows that
word on most tasks of every session, so the key would have called more reviews here, not fewer. The
executors' `submit` calls passed `--introduces` once in `cost-C-1`, never in `cost-C-2` and once in
`cost-C-3` (the introduces command), and the helper grades a missing-symbol error `could-not-prove`
without it. A phase-level signal is the other shape. Built from the facts above, an existing test
file changed or a `missing` input, it fires in `cost-C-1` and `cost-C-3`, and would have skipped
`cost-C-2`'s review, `0.1645`. Adding the recorded open choices, which the design's T9 made a
question of the review, fires in `cost-C-2` as well.

**The verdict, for the user's first priority.** The design's value test (its section 5.4) said that
nothing above low and no departure caught would make "the review only on a computed signal" the
user's decision. These sessions meet that condition. They also show what a signal would have saved:
nothing with the driver's key, and one review in three with the phase-level facts. So the
recommendation is to narrow it (lever D, section 6): the answers a script can give are computed, and
the facts that matched the grader go into the brief. Running the review on a signal, or not at all,
drops the per-task intent answer for the phase it skips, and the sign-off verb enforces that answer.
That is a guarantee P118 holds, so the choice stays the user's, priced at the review's `0.1560` to
`0.1652` a session.

The design's section 1.6 records the review before the change, when the project's reviewer was the
phase review: low findings only, one fixed, nothing graded moved.

## 4. The executor's hand-back, per cycle

The hand-back command reads each agent's tool result in the main loop. It splits the result into the
CLI's frame, the agent's report and the CLI's trailer (the `agentId` and `usage` lines), and prices
the agent's own output, the main loop's write of the result, and every later read of it. Output is
apportioned by emitted bytes inside a measured pool, so every output figure is an estimate.

| | `cost-C-1` | `cost-C-2` | `cost-C-3` | `probe-C-1` |
|---|---|---|---|---|
| each executor's hand-back, bytes | 1526, 1463, 2310 | 1952, 2614, 1801 | 1871, 2103, 1886 | 3703 |
| ...of which the CLI's frame and trailer | 671 in each | 671 in each | 671 in each | 671 |
| the line `submit` printed, which the prompt asks for | 142 to 151 | 151 | 142 to 151 | 142 |
| the executors' own output, estimate | `0.0293` | `0.0329` | `0.0325` | `0.0371`, on Opus |
| the main loop's write: tokens, then cost | 2528, `0.0202` | 3136, `0.0251` | 2769, `0.0221` | 1650, `0.0132` |
| the main loop's reads in the cycle | `0.0009` | `0.0013` | `0.0011` | `0` |
| **in the cycle** | **`0.0504`** | **`0.0593`** | **`0.0557`** | **`0.0503`** |
| the main loop's reads after the cycle | `0.0030` | `0.0038` | `0.0039` | `0.0007` |

The cycle figures equal the results document's hand-back share. The reads after the cycle are new
here: they are phase overhead. The phase reviewer's hand-back adds `0.0060` to `0.0091` of its own
output and `0.0044` to `0.0067` of main-loop write (the same command, its `reviewer` line).

**The results document's one-line estimate was wrong.** It took 80 tokens of output and write per
hand-back and gave 1.23, 1.31 and 1.17 like for like. The main loop receives the frame and trailer
whatever the agent writes, 671 bytes a hand-back, and the estimate left them out. Re-derived on the
bytes, the residual is the frame, the trailer and the line, and the agent's own output keeps the
line's share of its report. A cycle then saves `0.0364`, `0.0457` and `0.0422`, which is 1.254,
1.333 and 1.189 like for like (the prediction command). `cost-C-1` stays `0.0017` over the ideal's
`0.5276`.

## 5. `CLAUDE.md` in each agent's start

The arm C fixture's `CLAUDE.md` is 2193 bytes, with one digest in all three fixtures (`shasum -a 256
<fixture>/CLAUDE.md`). `measure-context.py --claude-md` counts it in the executor's and the
reviewer's starts (the measure command). In tokens it is an estimate: 548 at four bytes a token, 834
at the 2.63 the design calibrated on the plugin's prose. No recorded session read the file with a
tool, so no cache write of it alone exists to calibrate on (the corpus command's item scan).

**Where it sits in a start is not documented** (the design's section 9, "the order of a subagent's
initial context"). Each later executor re-wrote 6408 to 6524 tokens of its start and read 6270 from
cache (the stream command's `dispatches` lines). That bounds the cost a cycle pays for the file. If
each dispatch writes it, that is `T × 2.5e-6` for each of three dispatches plus `T × 0.2e-6` for
each later request. If only the first does, the later ones read it instead. At 834 tokens that is
`0.0103`, `0.0098` and `0.0099` a cycle on the first bound, and `0.0064`, `0.0059` and `0.0061` on
the second. At 548 tokens it is `0.0067` to `0.0039`. The phase reviewer adds `0.0028` at 834 (the
CLAUDE.md arithmetic). At most that moves the per-task ratio by 0.024.

**Which rules the prompts and briefs restate.** The rules command matches a key for each rule
against both agents' prompts at `1dd702f2` and against every computed brief in the three fixtures.
Each hit was then read by hand, and the table holds what that reading kept.

| `CLAUDE.md` rule | the executor's prompt | the executor briefs | where the rest of the guarantee lives |
|---|---|---|---|
| Python 3.8, standard library only | no | none | nowhere |
| the test command | no | every brief, as the task's gate | the driver's recorded gate runs it after each task |
| money through `shop.money` | no | most, where the description named it | the planner's choice per task |
| days through `shop.dates`, policy in `shop/policy.py` | no | about half | the same |
| persistence through `store.transaction` | no | the first two tasks' | the same |
| errors as `ShopError` subclasses | no | about half | the same |
| the event log through `events.record` | no | every brief | the same |
| stock through `shop.inventory` | no | most | the same |
| the CLI's `cmd_<verb>` and `parse_items` | no | about half | the same |
| `shop/legacy_refunds.py` left alone | no | each P1.1 brief | the same |
| 1: reuse the existing helper | no | none | nowhere; the grader's `reimplemented` flags check it |
| 2: change only what the request needs | "do not exceed its scope" | none | the plan gate holds the file scope; nothing holds a drive-by inside a file |
| 3: never edit an existing test to pass | no | `cost-C-3`'s, and `cost-C-1`'s P1.3 | the planner's choice; the reviewer's inherited-tests question |
| 4: the full test command after the last edit | the opposite: its own tests only | none | the driver's recorded gate |
| 5: state only what you ran | "a verification claim carries its evidence" | none | the filed return's shape |

**The verdict.** "Leave it out where the brief already carries the rules" never applied: no brief
carried every rule. None carried the standard-library rule or rule 1, and rule 1 is what separated
arm A from arms B and C. Moving the file into the brief would move the same bytes and save nothing.
So `omitClaudeMd` is not recommended for the executor or the reviewer. What it would have bought is
priced above, so the decision stays checkable.

## 6. The levers

Each lever names what it deletes or replaces, the guarantee it keeps and how that is checked, the
offline micro-test that confirms it before any paid session, and its predicted saving with the basis
of that figure. Effort and blast radius are stated as facts about each lever, never as the reason
for it.

### A — The plan batch on stdin

- **Mechanism.** `audit-task.py add --from-file -` reads the batch from stdin. The add form in
  `commands/phase.md` shows it as a quoted heredoc, the way `drive-phase.py submit` already takes a
  return. Today the form says to write the batch "outside the tracked tree" with the Write tool, and
  `read_batch()` opens only a path (`plugins/audit/scripts/manifest/audit-task.py` at this commit).
- **Deletes.** The batch file, the shared `/tmp` path two sessions collided on, and the fallback
  through flags that lost the request and the open choices.
- **Guarantee kept.** The batch goes through the same `read_batch` checks, and the manifest is
  revalidated, as every mutating command must. The request and the open choices are saved on every
  path, where today the fallback drops them, so this strengthens one.
- **Micro-test**, in `plugins/audit/tests/test_audit_task.py`:
  1. the same batch on stdin and from a file writes byte-identical manifests, with `request` present
     and each open choice counted;
  2. the refusal twin: a malformed batch on stdin is refused, naming the field, and the manifest's
     bytes are unchanged;
  3. `tools/measure-context.py --gate` still holds `/audit:phase add` under its ceiling with the new
     form;
  4. the write guards' own suites, given the heredoc command as their payload, refuse nothing.
- **Predicted saving.**
  - `cost-C-2`: requests 5 to 7, `0.1562`, measured. The plan is typed once, at request 4, as it
    was.
  - `cost-C-3`: requests 6 to 15, `0.5068`, less one request that types and adds the plan. That
    request is estimated at `cost-C-1`'s request 4, `0.1171`, whose prefix was 27988 tokens against
    29665 here. That leaves `0.3897`. The run form re-invoked at request 16 is kept, which
    understates the saving.
  - `cost-C-1`: none.
- **Facts.** It touches `audit-task.py`, the add form, and the task suite. A new value of an
  existing flag is additive.

### B — The hand-back line printed where the agent last reads

- **Mechanism.** `drive-phase.py submit` already prints the line the executor is asked to hand back.
  It follows that line with a second one: hand back the line above as the whole reply. When `submit`
  refuses, the second line says to hand back the refusal verbatim. The prompts' closing sentence
  about the hand-back goes, since the print now carries it. This applies to the executor and to the
  phase reviewer's `submit --head`.
- **Deletes.** The prose report the main loop writes once and reads to the end of the session. It
  replaces nothing. The driver is a script the main loop calls, so it never sees a hand-back; it
  reads the filed return (`filed()` in `drive-phase.py`).
- **Guarantee kept.** The return's shape check, red-first run, stamp and single filing are
  untouched. A refusal still reaches the main loop verbatim.
- **Not taken: a stop hook that blocks a long hand-back.** A hook on the subagent's stop could
  refuse a long report and make the agent write again. Whether the host honours that refusal from a
  plugin's hook is not probed in this repository. Either way the refusal arrives after the long
  report is written, so the agent pays for that report and for one more request. The hand-back
  command prices that request from each final's own prefix, and the trade comes out negative in
  every session: `−0.0131`, `−0.0088` and `−0.0109` a cycle against today. The hook would make the
  rule enforced at a price, and it saves nothing. So the rule stays followed. The hand-back
  command's report bytes in each benchmark are its reading, and nothing enforces it.
- **Micro-test**, in `plugins/audit/tests/test_drive_phase.py`:
  1. after a filed return, the last line of `submit`'s output is the instruction, and the line
     before it is the filed line, which occurs once;
  2. the refusal twin: a refused `submit` prints the refusal and the instruction to hand it back
     verbatim, and never names a filed line;
  3. `tools/measure-context.py --gate` holds both agents under their ceilings with the sentence
     gone.

  Whether agents follow the print can only be read in a paid session. The probe confirms B when
  every report is at most twice the line (the adverse estimate below).
- **Predicted saving**, if followed. It is an estimate, scaling the bytes the main loop receives and
  the agent's report to the line:
  - in the cycle: `0.0364`, `0.0457` and `0.0422`;
  - after it: `0.0071`, `0.0144` and `0.0122`, the executors' reads and the reviewer's hand-back.
- **Facts.** It touches `drive-phase.py`, both agent prompts, and the driver suite.

### C — Sign-off answered in advance

- **Mechanism.** At the phase reviewer's dispatch, the driver also prints the call to send after it:
  `next <phase> --answer sign-off --reason <the summary>`. That answer applies only when the triage
  it would answer has one admissible answer. If the review files `clean` with no finding open, no
  answer waiting on a human and no fix task after its head, `fix`, `accept`, `decline` and
  `re-review` are each refused, and only `sign-off` is left (`answer_refusal()` and
  `triage_refusal()` in `drive-phase.py` at `1dd702f2`). Otherwise the triage is printed as today
  and the answer is reported as not applied.
- **Deletes.** One main-loop request at sign-off. In a clean phase the triage request carries a
  decision with a single answer.
- **Guarantee kept.**
  - The sign-off verb, the phase gate, the invariants, the commit, the landing and the lock release
    run unchanged.
  - The main loop still sends the answer, with its own reason, and can still hold the landing by not
    sending it.
  - A finding, an answer for a human, or an unreviewed fix task still stops at the triage.
- **Micro-test**, in `plugins/audit/tests/test_drive_phase.py`:
  1. a clean review answered in advance signs off and prints `done` in the one call;
  2. the refusal twins: with a finding open, or with an answer waiting on a human, the same call
     prints the triage and runs no sign-off;
  3. `tools/stream-cost.py --selftest`'s driven-span cases still place the landing in the close.
- **Predicted saving.** An estimate: one request, taken at the cheaper of the two it merges, the
  triage request or the sign-off answer. That is `0.0168`, `0.0199` and `0.0218`.
- **Facts.** It touches `drive-phase.py` and its suite. The refusal `no decision is pending` becomes
  an acceptance in the one state above and stays everywhere else. No case asserts it today:
  `grep -n 'no decision is pending' plugins/audit/tests/test_drive_phase.py` prints nothing.

### D — The review's mechanical answers, computed

- **Mechanism.** Two of each task's three answers are mechanical today:
  - when the executor's red-first is the helper's block, the reviewer is told to echo it;
  - when `tests.gate` runs the whole project, the inherited-tests answer is `not-asked`.

  The filing verb fills both into the phase return from those sources. The reviewer's prompt keeps
  them only for the cases that need reading: a red-first the helper did not grade, and a gate that
  selects named tests. The phase brief also gains the computed list of existing test files the
  phase's diff modifies. That is the fact section 3 found matching the grader's flag.
- **Deletes.** The typed copies of those fields. They are 34 %, 36 % and 39 % of each filed phase
  return's bytes (the return command).
- **Guarantee kept.** Each task's recorded words are the same, now copied by a script from enforced
  sources. The intent answer stays the reviewer's, and the sign-off verb still refuses until every
  owed task has one.
- **Micro-test**:
  1. a phase return filed without the mechanical fields is completed from the executor's filed block
     and the gate's shape;
  2. the refusal twins: a task whose gate selects named tests, and a red-first the helper did not
     grade, are each refused without the reviewer's answer;
  3. the phase brief lists an existing test file that a fixture phase appends a test to, and not a
     new test file.
- **Predicted saving.** An estimate: those shares of the reviewer's typed return, `0.0327`, `0.0274`
  and `0.0302` (the dispatch command). That gives `0.0111`, `0.0099` and `0.0118`, apportioning
  output by bytes as the tool does. The brief's own reads shrink too, and that is not counted.
- **Facts.** It touches `_filed_returns.py` or the filing verb, `audit-lookup.py`'s phase brief, the
  reviewer prompt, and their suites.

### What is not recommended, and why

| Option | What it would save here | Why not |
|---|---|---|
| a stop hook that blocks a long hand-back | `−0.0131`, `−0.0088`, `−0.0109` a cycle: a cost | section 6, lever B |
| the phase review on a computed signal | none with the driver's `signals` key; `cost-C-2`'s `0.1645` with phase-level facts | section 3: it gives up the intent answer for the phase it skips |
| the phase review off | `0.1560`, `0.1645`, `0.1652` a session | it drops the per-task intent answer the sign-off verb enforces: the user's decision |
| `omitClaudeMd` for the agents | at most an estimated `0.0103` a cycle | section 5: no brief carries every rule |
| keeping the main loop out of the diff in the cycle | `cost-C-2`'s `0.0462` (the results document's section 5.1) | no mechanism: a guard would read the command's words, and a refused read gets routed round. It happened in one session of three |
| a later executor's start served from cache | an estimated `0.015` a later dispatch: 6408 to 6524 tokens written at `2.5e-6` that a cache read takes at `0.2e-6` | what in a start varies between dispatches is not documented (the design's section 9), so there is nothing to build yet |

### 6.1 Predicted ratios

The prediction command applies each lever's saving to the measured figures. A, C and D act on the
phase overhead, and B on both the cycle and the overhead.

| | Per task, like for like | Phase overhead | Phase overhead ÷ A | Whole session ÷ A |
|---|---|---|---|---|
| `cost-C-1` | 1.34 → 1.254 | `0.6003` → `0.5653` | 1.19 → 1.12 | 2.58 → 2.44 |
| `cost-C-2` | 1.44 → 1.333 | `0.7505` → `0.5501` | 1.49 → 1.09 | 2.95 → 2.46 |
| `cost-C-3` | 1.29 → 1.189 | `1.1451` → `0.7096` | 2.27 → 1.41 | 3.61 → 2.66 |

The phase overhead budget, 1.00, is met in every session, and lever A alone meets it. The per-task
ceiling of 2.0 is met. The 1.25 ideal is met in `cost-C-3`. `cost-C-1` is `0.0017` over it. In
`cost-C-2` the main loop's own diff reads in the cycle are more than its gap, and no lever above has
a mechanism for them.

### 6.2 Each estimate taken the adverse way

Each estimate is moved against the target, one at a time: a cost doubled, or a saving halved where
the estimate is the saving (the prediction command). Each cell is the per-task ratio, then the phase
overhead.

| Estimate | `cost-C-1` | `cost-C-2` | `cost-C-3` |
|---|---|---|---|
| A: the request that replaces the fallback doubled; for `cost-C-2`, one more request at its request 5's `0.0449` | 1.25 / `0.5653` | 1.33 / `0.5950` | 1.19 / `0.8267` |
| B: the line kept at twice its bytes | 1.27 / `0.5681` | 1.35 / `0.5520` | 1.20 / `0.7118` |
| B: not followed at all | 1.34 / `0.5724` | 1.44 / `0.5645` | 1.29 / `0.7218` |
| C: half a request saved | 1.25 / `0.5737` | 1.33 / `0.5601` | 1.19 / `0.7205` |
| D: half the share saved | 1.25 / `0.5708` | 1.33 / `0.5551` | 1.19 / `0.7155` |

No row takes a session's phase overhead past 1.00 or a per-task ratio past 2.0. The highest reading
is `cost-C-3` with A's request doubled, `0.8267`.

### 6.3 What the paid sessions must read

Each micro-test above must pass first. Then one paid probe, and then the full benchmark, both run by
the orchestrator, read:

- the phase overhead by the step command, against 1.00 in every session;
- the per-task ratio by the stream command's cycle, against 2.0 and toward 1.25;
- planning's requests, and whether any write was refused (the calls command), which is A's reading;
- each agent's report bytes, against twice the line (the hand-back command), which is B's reading;
- sign-off's main-loop requests (the stream command's `sign-off` span), which is C's reading;
- the phase return's fields, which is D's: computed where the rule is mechanical, the reviewer's
  where it is not (the return command).

## 7. Limits

- **Three sessions an arm, one observation each.** Nothing here is a rate, and a lever's prediction
  holds only for sessions shaped like these.
- **Output is apportioned by bytes** within each measured pool, so every output figure is an
  estimate. The hand-back's rebuilt final is apportioned on the whole result's bytes, which counts
  the CLI's frame as emitted. That overstates its output by the frame's share.
- **B's effect cannot be measured offline.** The micro-test shows the print exists, and only a paid
  session shows that agents follow it.
- **C and D are priced on one request and one return each**, the cheapest reading the sessions
  allow. A paid session reads them directly.
- **The fixture is one project.** The rules table reads its `CLAUDE.md`, and another project's rules
  and briefs would read differently.

## 8. Re-deriving every figure

| Figure | Command |
|---|---|
| totals, spans, the cycle, `dispatches` | the **stream command**: `python3 tools/stream-cost.py <x3>/<label>/stream.jsonl`, and for `cost-C-3` both streams, `<x3>/cost-C-3/stream.jsonl <x3>/cost-C-3/stream-followup-1.jsonl`; `--json` for the unrounded figures |
| the refusal, the byte-identical reports, the joined `cmp`, and the item scan | the corpus command |
| each step of a session | the step command |
| the driver calls' seconds and bytes | the call-time command |
| the hand-backs, and lever B | the hand-back command, with the line at 1 and at 2 |
| a dispatch's parts, among them the reviewer's typed return | the dispatch command |
| the phase reviews' answers, and the share of their fields a script can give | the return command |
| what changed after the review's head | the after-review command |
| what the project's reviewer reported | the reviewer-text command |
| the existing test files a session modified | the existing-test command |
| `submit` calls passing `--introduces` | the introduces command |
| `CLAUDE.md` in each start, in bytes and estimated tokens | the measure command |
| its cost a cycle, both bounds | the CLAUDE.md arithmetic |
| which rules the prompts and briefs restate | the rules command, then each hit read by hand |
| the predictions and the adverse table | the prediction command |

The **corpus command** runs the tool over every recorded stream. It lists the ones it refuses, and
compares each report with the one the commit before this document's printed, from a `git archive`
export in `<scratch>`. Then it compares the two-stream reading of `cost-C-3` with its concatenation.

```
for f in $(find <analysis>/experiments -name 'stream*.jsonl' | sort); do
  python3 tools/stream-cost.py "$f" > <scratch>/now.txt 2> <scratch>/now.err || { echo "refused: $f"; cat <scratch>/now.err; }
  python3 <scratch>/before/tools/stream-cost.py "$f" > <scratch>/before.txt 2>&1
  cmp -s <scratch>/now.txt <scratch>/before.txt || echo "differs: $f"
done
cat <x3>/cost-C-3/stream.jsonl <x3>/cost-C-3/stream-followup-1.jsonl > <scratch>/joined.jsonl
for flag in "" --json; do
  python3 tools/stream-cost.py $flag <scratch>/joined.jsonl > <scratch>/a
  python3 tools/stream-cost.py $flag <x3>/cost-C-3/stream.jsonl <x3>/cost-C-3/stream-followup-1.jsonl > <scratch>/b
  cmp <scratch>/a <scratch>/b && echo "identical ${flag:-text}"
done
```

`<scratch>/before` is `git archive <the commit before this document's> | tar -x -C
<scratch>/before`. For the item scan, run `--json` on each stream and print every `items` entry
whose `source` names `CLAUDE.md`. It printed none.

The **step command** takes a step map and the streams. In the map, `name=first-last` entries are
separated by `;`. It prints each step's main-loop and agent cost, keeps the project's `reviewer`
agent apart, and ends with the totals. The maps for the tables in section 2:

- `cost-C-1`:
  `start=1;reads=2-3;plan=4;cycle=5-11;review=12;triage=13;diff=14;sign-off=15;project=16;report=17`
- `cost-C-2`:
  `start=1;reads=2-3;plan=4;recovery=5-7;cycle=8-14;review=15;triage=16;sign-off=17;suite=18;project=19;report=20`
- `cost-C-3`:
  `start=1;reads=2-4;question=5;fallback=6-15;run-form=16;cycle=17-23;review=24;triage=25;diff=26;project=27;sign-off=28;suite=29;report=30`
- `probe-C-1`: `cycle=1-3;status=4;report=5`

```
python3 - '<map>' <stream> [<follow-up>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
events, problem = sc.load_streams(sys.argv[2:])
if problem: raise SystemExit(problem)
r = sc.analyse(events); c = r["costs"]; ag = r["session"]["agents"]
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
grand = [0.0, 0.0]
for part in sys.argv[1].split(";"):
    name, spans = part.split("=")
    nums = [n for span in spans.split(",") for lo, _, hi in [span.partition("-")] for n in range(int(lo), int(hi or lo) + 1)]
    ids = set(main[n - 1]["id"] for n in nums); sent = [t for t, a in ag.items() if a["request"] in ids]
    m = sum(c[i]["total"] for i in ids)
    plug = sum(c[x["id"]]["total"] for x in r["requests"] if x["context"] in sent and ag[x["context"]]["type"] != "reviewer")
    proj = sum(c[x["id"]]["total"] for x in r["requests"] if x["context"] in sent and ag[x["context"]]["type"] == "reviewer")
    grand[0] += m + plug; grand[1] += proj
    print("%-10s %-6s main %.4f agents %.4f step %.4f%s" % (name, spans, m, plug, m + plug, "  the project's reviewer apart %.4f" % proj if proj else ""))
print("steps %.4f + the project's reviewer %.4f; the session %.6f" % (grand[0], grand[1], sum(x["total"] for x in c.values())))
EOF
```

The **call-time command** prints each driver call in the main loop, with the seconds from the call's
event to its result's, and the bytes it printed.

```
python3 - <stream> [<follow-up>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
events, problem = sc.load_streams(sys.argv[1:])
n, calls = {}, {}
for e in events:
    m = e.get("message") if isinstance(e.get("message"), dict) else {}
    if e.get("parent_tool_use_id") or not isinstance(m.get("content"), list): continue
    if e.get("type") == "assistant":
        i = n.setdefault(m["id"], len(n) + 1)
        for c in m["content"]:
            if c.get("type") == "tool_use" and "drive-phase" in str((c.get("input") or {}).get("command")):
                cmd = c["input"]["command"]; calls[c["id"]] = (i, sc._ts(e.get("timestamp")), " ".join(cmd[cmd.find("drive-phase.py") + 15:].split())[:40])
    for c in m["content"] if e.get("type") == "user" else []:
        if isinstance(c, dict) and c.get("tool_use_id") in calls:
            i, t0, what = calls[c["tool_use_id"]]; x = c.get("content")
            text = x if isinstance(x, str) else "".join((b.get("text") or "") for b in x)
            print("request %2d %5.1f s %4d B  %s" % (i, sc._ts(e.get("timestamp")) - t0, len(text.encode()), what))
EOF
```

The **hand-back command** takes the cycle's first and last request, the multiple of the line to keep
(1 and 2 here), and the streams. For each executor and phase reviewer it prints the result's bytes
by part, `submit`'s line, the agent's own output, and the main loop's write and reads in and after
the cycle. It then prints lever B's saving if followed, and if blocked once instead. Its totals
print per agent type.

```
python3 - <first> <last> <k> <stream> [<follow-up>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
import _usage_core
lo, hi, k = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
events, problem = sc.load_streams(sys.argv[4:])
if problem: raise SystemExit(problem)
r = sc.analyse(events); ag = r["session"]["agents"]; out = r["output"] or {}
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
pos = dict((q["id"], i + 1) for i, q in enumerate(main)); last = len(main)
texts, lines, submits = {}, {}, set()
for e in events:
    m = e.get("message") if isinstance(e.get("message"), dict) else {}
    for c in m.get("content") if isinstance(m.get("content"), list) else []:
        cmd = str((c.get("input") or {}).get("command"))
        if c.get("type") == "tool_use" and e.get("parent_tool_use_id") and "drive-phase" in cmd and "submit" in cmd: submits.add(c["id"])
        if c.get("type") == "tool_result":
            x = c.get("content"); t = x if isinstance(x, str) else "".join((b.get("text") or "") for b in x)
            if c.get("tool_use_id") in ag: texts[c["tool_use_id"]] = t
            elif c.get("tool_use_id") in submits and not c.get("is_error") and t.strip():
                said = [l for l in t.splitlines() if l.startswith("[drive-phase]")]
                lines[e["parent_tool_use_id"]] = said[-1] if said else t.strip().splitlines()[-1]
KEYS = ("own", "tok", "w", "rc", "ra", "sc", "sa", "bc", "ba")
tot = dict((kind, dict.fromkeys(KEYS, 0.0)) for kind in ("executor", "reviewer"))
for tid, a in sorted(ag.items(), key=lambda kv: pos.get(kv[1]["request"], 0)):
    if a["context"] != sc.MAIN or a["type"] not in ("audit:audit-executor", "audit:audit-reviewer"): continue
    at = pos[a["request"]]; enters = at + 1; in_cycle = enters <= hi
    t = texts.get(tid, ""); whole = len(t.encode())
    j = t.find("The report follows:"); frame = len(t[:j + 19].encode()) if j >= 0 else 0
    j = t.find("agentId:"); trailer = len(t[j:].encode()) if j >= 0 else 0
    report, line = whole - frame - trailer, len(lines.get(tid, "").encode()) or 151
    fin = [q for q in r["requests"] if q["context"] == tid and q["reconstructed"]]; rate = _usage_core.rates_for(fin[0]["model"])
    own_tok = sum(out.get(q["id"], 0.0) for q in fin); own = own_tok * rate["out"] / 1e6
    items = [it for it in r["content"]["items"] if it["request"] in pos and not it.get("base")
             and it["source"].startswith("hand-back of " + a["type"]) and pos[it["request"]] == enters]
    tok = sum(it["tokens"] for it in items); w = sum(it["writeUSD"] for it in items)
    rc = tok * max(0, hi - enters) * 0.2e-6 if in_cycle else 0.0
    ra = tok * (last - max(enters, hi)) * 0.2e-6
    keep = (frame + k * line + trailer) / float(whole); own_keep = own * min(1.0, k * line / float(report))
    main_c, main_a = ((w + rc) if in_cycle else 0.0), ra + (0.0 if in_cycle else w)
    extra = ((fin[0]["cr"] + fin[0]["cw5"] + fin[0]["cw1"]) * rate["cacheR"] + own_tok * rate["cacheW5m"] + k * line / 2.63 * rate["out"]) / 1e6
    sc_, sa_ = main_c * (1 - keep), main_a * (1 - keep)
    if in_cycle: sc_, bc_, ba_ = sc_ + own - own_keep, main_c * (1 - keep) - extra, sa_
    else: sa_, bc_, ba_ = sa_ + own - own_keep, 0.0, main_a * (1 - keep) - extra
    for key, v in zip(KEYS, (own, tok, w, rc, ra, sc_, sa_, bc_, ba_)): tot[a["type"][12:]][key] += v
    print("at %2d %-9s %4d B: frame %3d, report %4d, trailer %3d; line %3d B | own %.4f | main loop %4.0f tok, write %.4f, reads %.4f in the cycle, %.4f after" % (
        at, a["type"][12:], whole, frame, report, trailer, line, own, tok, w, rc, ra))
for kind, t in sorted(tot.items()):
    print("%s: own %.4f; main loop %.0f tok, write %.4f, reads %.4f + %.4f | line x%.0f saves %.4f in the cycle, %.4f after | blocked once: %.4f, %.4f" % (
        kind, t["own"], t["tok"], t["w"], t["rc"], t["ra"], k, t["sc"], t["sa"], t["bc"], t["ba"]))
both = [tot["executor"][key] + tot["reviewer"][key] for key in ("sc", "sa", "bc", "ba")]
print("both: line x%.0f saves %.4f in the cycle, %.4f after | blocked once: %.4f, %.4f" % tuple([k] + both))
EOF
```

The cycle bounds are `5 11`, `8 14`, `17 23`, and `1 3` for the probe. The line falls back to 151
bytes only where no `submit` line was found. That happened for no agent in these sessions.

The **dispatch command** splits each dispatch's billed cost into its start, its brief reads, and its
output by kind: the return typed into `submit`, the hand-back, code written, and the rest. It is the
results document's parts command, applied to one dispatch at a time.

```
python3 - <stream> [<follow-up>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
import _usage_core
r = sc.analyse(sc.load_streams(sys.argv[1:])[0]); c = r["costs"]; ag = r["session"]["agents"]
main = [q for q in r["requests"] if q["context"] == sc.MAIN and not q["reconstructed"]]
pos = dict((q["id"], i + 1) for i, q in enumerate(main))
for t, a in ag.items():
    qs = [q for q in r["requests"] if q["context"] == t]
    if a["context"] != sc.MAIN or not qs: continue
    rate = _usage_core.rates_for(qs[0]["model"]); ids = set(q["id"] for q in qs)
    items = [it for it in r["content"]["items"] if it["request"] in ids]
    start = sum(it["writeUSD"] + it["carryUSD"] for it in items if it["source"].startswith("agent start"))
    brief = sum(it["writeUSD"] + it["carryUSD"] for it in items if "/briefs/" in it["source"])
    o = dict(submit=0.0, handback=0.0, code=0.0, other=0.0)
    for q in qs:
        v = (r["output"] or {}).get(q["id"], 0.0) * rate["out"] / 1e6
        cmds = [(x["name"], str((x.get("input") or {}).get("command") or "")) for x in q["tools"]]
        o["handback" if q["reconstructed"] else "submit" if any("drive-phase" in y and "submit" in y for _n, y in cmds)
          else "code" if any(n in ("Write", "Edit", "MultiEdit") for n, _y in cmds) else "other"] += v
    total = sum(c[q["id"]]["total"] for q in qs)
    print("at %2d %-22s total %.4f | start %.4f brief %.4f | submit %.4f hand-back %.4f code %.4f other %.4f" % (
        pos[a["request"]], a["type"], total, start, brief, o["submit"], o["handback"], o["code"], o["other"]))
EOF
```

The **return command** reads each fixture's filed phase return, read-only. It prints the verdict,
the findings, every task's answers, and the share of the return's bytes a script could have given.

```
f=$(git -C <fixture> ls-tree -r --name-only main -- docs/audit/evidence/returns/P1/)
git -C <fixture> show "main:$f" | python3 -c "
import json, sys
d = json.load(sys.stdin); i = d['intent']; b = lambda x: len(json.dumps(x, ensure_ascii=False).encode())
keys = ('redFirst', 'redFirstBasis', 'inheritedTests', 'inheritedTestsBasis')
comp = sum(b(t.get(k)) + len(k) + 4 for t in d['tasks'] for k in keys) + sum(b(i.get(k)) + len(k) + 4 for k in keys + ('missing',) if k in i)
print('verdict', d['verdict'], '| findings', len(d['findings']), '| missing', i.get('missing'), '| computable %.0f%%' % (100.0 * comp / b(d)))
for t in d['tasks']: print(' ', t['id'], t['answer'], t['redFirst'], t['inheritedTests'])
"
```

The **after-review command** takes the reviewed head from the return's file name and lists every
file outside `docs/audit` that differs between it and the landed `main`.

```
h=$(git -C <fixture> ls-tree -r --name-only main -- docs/audit/evidence/returns/P1/ | sed 's|.*/||; s|\..*||')
git -C <fixture> diff --name-only "$h" main -- . ':(exclude)docs/audit'
```

The **reviewer-text command** prints the report of each dispatch of the project's `reviewer`.

```
python3 - <stream> [<follow-up>] <<'EOF'
import importlib.util as u, sys
s = u.spec_from_file_location("sc", "tools/stream-cost.py"); sc = u.module_from_spec(s); s.loader.exec_module(sc)
ids = {}
for e in sc.load_streams(sys.argv[1:])[0]:
    m = e.get("message") if isinstance(e.get("message"), dict) else {}
    for c in m.get("content") if isinstance(m.get("content"), list) else []:
        if c.get("name") in ("Agent", "Task") and not e.get("parent_tool_use_id"):
            ids[c["id"]] = c["input"].get("subagent_type")
        if c.get("type") == "tool_result" and ids.get(c.get("tool_use_id")) == "reviewer":
            x = c.get("content"); t = x if isinstance(x, str) else "".join((b.get("text") or "") for b in x)
            print(t[t.find("The report follows:") + 20:][:1500])
EOF
```

The **existing-test command** lists the test files that existed at the session's base and that it
modified. `<base>` is `<x3>/<label>/bench-meta.json` → `baseSha`.

```
git -C <fixture> diff --diff-filter=M --name-only <base> main -- tests
```

The **introduces command** counts, per session, the executors' `submit` calls that pass
`--introduces`.

```
python3 - <stream> [<follow-up>] <<'EOF'
import json, sys
n = 0
for path in sys.argv[1:]:
    for l in open(path, encoding="utf-8"):
        e = json.loads(l) if l.strip() else {}
        body = (e.get("message") or {}).get("content") if e.get("parent_tool_use_id") else None
        for c in body if isinstance(body, list) else []:
            cmd = str((c.get("input") or {}).get("command"))
            n += c.get("type") == "tool_use" and "drive-phase" in cmd and "submit" in cmd and "--introduces" in cmd
print(n)
EOF
```

The **measure command** is `python3 tools/measure-context.py --ref 1dd702f2 --claude-md
<fixture>/CLAUDE.md --bytes-per-token 2.63`, and again with `4`. Its `executor` and `reviewer`
entries each list `CLAUDE.md` at 2193 bytes.

The **CLAUDE.md arithmetic** reads each executor's request count from the `dispatches` lines (11, 8,
8; 10, 7, 7; 9, 8, 8) and the phase reviewer's (5 in each). With `T` the file's tokens:

```
python3 -c "
for name, reqs in (('cost-C-1', (11, 8, 8)), ('cost-C-2', (10, 7, 7)), ('cost-C-3', (9, 8, 8))):
    for T in (834, 548):
        each = sum(T * 2.5e-6 + T * (n - 1) * 0.2e-6 for n in reqs)
        first = T * 2.5e-6 + T * (reqs[0] - 1) * 0.2e-6 + sum(T * n * 0.2e-6 for n in reqs[1:])
        print(name, T, 'every dispatch writes it %.4f, the first only %.4f, the reviewer %.4f' % (each, first, T * 2.5e-6 + T * 4 * 0.2e-6))
"
```

The **rules command** prints, for each rule of the fixture's `CLAUDE.md`, whether its key matches
each agent prompt at `1dd702f2` and each computed brief under `<fixture>/.claude/state/briefs/`. A
match is where reading starts, not a verdict. A key matching a JSON field named `scope` or the word
"telescope" is not the rule, and the gate command in a brief is not rule 4. The table in section 5
is the reading.

```
python3 - <fixture> [<fixture> ...] <<'EOF'
import glob, os, re, subprocess, sys
RULES = [("3.8, stdlib", r"standard library|stdlib|python 3\.8"), ("test command", r"unittest discover -s tests -t \."),
         ("money", r"\bprorate\b|percent_of|money\.fmt|money\.parse"), ("days", r"shop\.dates|dates\.|days_between|parse_day|policy\."),
         ("transaction", r"transaction"), ("errors", r"ShopError|NotFound|InvalidRequest|ValueError"),
         ("events", r"events\.record|order\.refunded"), ("stock", r"inventory\.|restock"), ("cli", r"cmd_|parse_items"),
         ("legacy", r"legacy_refunds"), ("rule 1", r"existing helper|reuse|second one|re-?implement"),
         ("rule 2", r"drive-by|refactor|only what|scope"), ("rule 3", r"existing test|edit.{0,20}test|pinned"),
         ("rule 4", r"full (test|suite)|whole suite|discover -s tests"), ("rule 5", r"what you ran|what it printed|carries its evidence|verified")]
show = lambda p: subprocess.run(["git", "show", "1dd702f2:" + p], stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
docs = [("executor prompt", show("plugins/audit/agents/audit-executor.md")), ("reviewer prompt", show("plugins/audit/agents/audit-reviewer.md"))]
for root in sys.argv[1:]:
    for path in sorted(glob.glob(os.path.join(root, ".claude", "state", "briefs", "*", "*.md"))):
        docs.append(("%s %s" % (os.path.basename(root)[-8:], path.split(os.sep)[-2]), open(path, encoding="utf-8").read()))
for label, key in RULES:
    print("%-13s %s" % (label, " ".join("%-3s" % ("yes" if re.search(key, t, re.I) else "-") for _n, t in docs)))
for k, (name, _t) in enumerate(docs):
    print(k + 1, name)
EOF
```

The **prediction command** applies the savings above to the measured figures, and prints the table
in section 6.1, then the table in section 6.2.

```
python3 - <<'EOF'
LFL, A = 0.422075, 0.504523
S = {"cost-C-1": dict(cyc=0.5657, ovh=0.6003, tot=1.300077, b=(0.0364, 0.0071), b2=(0.0304, 0.0043), a=0.0, a2=0.0, c=min(0.0168, 0.0372), d=0.34 * 0.0327),
     "cost-C-2": dict(cyc=0.6084, ovh=0.7505, tot=1.487590, b=(0.0457, 0.0144), b2=(0.0403, 0.0125), a=0.1562, a2=0.1562 - 0.0449, c=min(0.0214, 0.0199), d=0.36 * 0.0274),
     "cost-C-3": dict(cyc=0.5442, ovh=1.1451, tot=1.819516, b=(0.0422, 0.0122), b2=(0.0367, 0.0100), a=0.5068 - 0.1171, a2=0.5068 - 2 * 0.1171, c=min(0.0218, 0.0374), d=0.39 * 0.0302)}
def after(x, **o):
    v = dict(x, **o)
    return x["cyc"] - v["b"][0], x["ovh"] - v["a"] - v["b"][1] - v["c"] - v["d"]
for name, x in sorted(S.items()):
    cyc, ovh = after(x); saved = x["cyc"] - cyc + x["ovh"] - ovh
    print(name, "per task %.3f -> %.3f; overhead %.4f -> %.4f (%.2f -> %.2f of A); whole %.2f -> %.2f of A" % (
        x["cyc"] / LFL, cyc / LFL, x["ovh"], ovh, x["ovh"] / A, ovh / A, x["tot"] / A, (x["tot"] - saved) / A))
for label, f in (("A", lambda x: dict(a=x["a2"])), ("B x2", lambda x: dict(b=x["b2"])), ("B none", lambda x: dict(b=(0.0, 0.0))),
                 ("C half", lambda x: dict(c=x["c"] / 2)), ("D half", lambda x: dict(d=x["d"] / 2))):
    print(label, "  ".join("%.2f / %.4f" % (lambda p: (p[0] / LFL, p[1]))(after(x, **f(x))) for _n, x in sorted(S.items())))
EOF
```

Its inputs are figures printed above:

- the cycles, the phase overheads and the totals, by the stream and step commands;
- B's savings at the line and at twice it, by the hand-back command;
- A's requests 5 to 7, 6 to 15 and 4, and C's two requests, by the step command;
- D's shares and typed returns, by the return and dispatch commands.
