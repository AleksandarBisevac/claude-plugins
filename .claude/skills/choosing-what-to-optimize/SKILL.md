---
name: choosing-what-to-optimize
description: Decide what is worth making faster in this repo, and prove it paid — measure the thing instead of grepping for it, separate wall clock from total CPU from the critical path, rank targets by shape rather than by how many modules import them, and decline the work with a number when the number says so. Use this whenever someone asks to speed up the tests, the sweep, the gates, CI or a hook; when a profile or a grep suggests a hot spot; when a refactor is justified by "this file is bad" rather than by a measurement; and before deferring or closing a performance item — even when the request sounds like ordinary cleanup rather than optimization.
---

# Choosing what to optimize

Everything here was paid for. The figures are from one pass over this repo's own test
machinery, and every one of them carries the command that re-derives it, because a number
in a document is a number that rots.

The short version: **the repo has no cheap 20% lying around.** What it has is a handful of
suites doing real work against real git and real browsers. So the value of an optimization
pass here is mostly in *not* doing the wrong one.

## Measure the thing; do not grep for it

Three findings in one session were reported wrong, each because a grep stood in for a run:

| claimed | actual | why the grep lied |
|---|---|---|
| 38 `subprocess` calls in a suite | **453** child processes | the grep counted textual occurrences; most calls span lines and most spawns come from the code under test |
| 1 tool without a test suite | **3** | all three printed a *pointer* containing `--selftest`, so the grep matched the word and missed the absence |
| 0 section markers in an 8000-line file | **42** | the lint's own regex allows two spaces of indentation; the grep was anchored at column 0 |

The third was the expensive one: it was the premise of a plan. The lint would have passed on
that file, so the rule being added to force a split would have forced nothing.

Ask the subject, not a proxy for it: run the profiler, call the lint function, count the
processes. When a claim is about a rule, **ask the rule** — import the module and call it
rather than reimplementing its pattern in a grep.

## Three numbers, not one

"Slow" is three different measurements and they lead to three different decisions.

```bash
python3 tools/sweep-selftests.py             # wall clock: what you wait for
python3 tools/sweep-selftests.py --jobs 1    # the serial shape, for a bisect
```

```python
# total child CPU: what a 2-core CI runner pays, since its wall clock is ~CPU/2
import resource, subprocess, sys, time
b = resource.getrusage(resource.RUSAGE_CHILDREN); t0 = time.time()
subprocess.run([sys.executable, "tools/sweep-selftests.py"], capture_output=True)
a = resource.getrusage(resource.RUSAGE_CHILDREN)
print(time.time() - t0, (a.ru_utime - b.ru_utime) + (a.ru_stime - b.ru_stime))
```

The sweep measured 11.4s wall against 52.6s of child CPU. Those are not the same fact:

- **Wall clock** is bounded below by the slowest single file, because each file is one
  process. Parallelism buys wall clock and nothing else.
- **Total CPU** is what CI pays. This repo's CI runs the sweep four times (two passes ×
  two operating systems), so CPU is multiplied by four and divided by the runner's cores.
- **The critical path** is the slowest file. Nothing below it can move the wall clock,
  however hot it looks in a profile.

A change that halves a file which is not the critical path improves the wall clock by
exactly zero. Say which of the three numbers your change moves, before making it.

## Do not optimize off the critical path

The worked example is a decision to *decline*.

`_deps._scan_edges` parses every `.py` under `scripts/` and grows a wrapper map to a
fixpoint. Six files import that graph, and each pays one scan of roughly 0.9s — **8.89s of
the sweep's 52.6s of CPU, about 17%.** Hoisting the per-tree walk out of the fixpoint would
recover most of one scan, so call it **~10.6% of CPU and 0s of wall clock**, because the
critical path is a different suite entirely.

Against that: the fixpoint decides the runtime-load edges of the import graph, which every
layer lint and the whole `affected.py` selector read. It is the subtlest code in the module,
and it carries a written argument for *why* it must be a fixpoint rather than two passes.

So it was closed as won't-do. Ten percent of CPU, none of the wall clock, on the code that
underpins every layer lint, is the worst risk-to-reward ratio available.

**And then the rule was broken by the person who had just written it.** The "free" version —
make a verification block pay for one tree scan instead of three — produced two defects in
ten minutes: one seeded a cache from the same value the case compares it against, so the
check compared a value with itself and could no longer fail; the other saved nothing and left
behind a comment claiming a saving. Both were reverted. The lesson is not that the attempt was
careless. It is that a micro-optimization off the critical path has no upside to pay for its
mistakes.

## Rank by shape; coupling is a cost, not a reason

A composite score that sums *shape* metrics with *coupling* ranks the popular, not the bad.
Scored that way, the top target came out as the module 80 others import — which had one long
function and clean metrics otherwise. It ranked first for being depended upon.

Separate the axes. Score shape only — longest function, functions over N lines, parameter
count, repeated literals, branch density per 100 lines — and print fan-in/fan-out **beside**
it as the cost of touching the file. That is the same rule this repo applies to recommending
options: effort and blast radius are facts about a choice, never the reason for it.

Then read the file before believing the score. On the re-ranked first place, most of the
score did not survive inspection:

- "25 short names" were `k`, `p`, `t`, `a`/`b` — loop and comprehension variables. The metric
  counted 25 *distinct* names, not 25 bad ones.
- seven of eight "repeated literals" were **dict keys** (`"findings"` at 39 sites). That is a
  key name used at every construction site, not a duplicated fact, and `out[_FINDINGS]` would
  read worse at all 39.
- the eighth was a duplicated *return value*, four byte-identical copies of one refusal. That
  one was real, and it was one extraction.

A mechanical rank is a pointer, not a verdict. Inspecting the pointer is what turns it into
work — and roughly one metric in eight survived that inspection here.

## A saving spent is not a saving lost, but you have to report both

The same pass memoised a scan and cut one suite from 16.3s to about 3s. The serial sweep
went from 44.0s to 41.9s.

That is not a contradiction and it is not a disappointment: the ~10s the memo returned was
spent on 8 more files and 126 more cases in the same pass. Reporting only the suite's 5×
would overstate it; reporting only the 2s would understate it. Report the pair — what the
change returned, and what the same pass spent — or the number lies in one direction or the
other.

## Decline with a number

"We did not get to it" and "10.6% of CPU, 0s of wall clock, on the code every layer lint
depends on" are different decisions. The first cannot be revisited, because nothing in it
says what would have to change. The second can: it names a threshold, so a future reader who
finds the critical path elsewhere, or CI paying for eight cores, knows exactly which
assumption to re-measure.

Write the deferral as a measurement, and name the trigger that would reopen it.

## Where the costs actually are

Re-derive rather than trusting this table — the point of listing the commands is that the
shape of the answer changes as the tree grows.

| cost | how to see it |
|---|---|
| the sweep's wall clock, and its slowest file | `python3 tools/sweep-selftests.py` prints one row per file |
| total CPU, and therefore CI | the `getrusage` snippet above |
| the panel browser gate — by far the longest single leg | `node tools/capture-screenshots.mjs --check` |
| the report gate | `node tools/check-report-interactive.mjs docs/index.html` |
| which gates a change actually owes | `python3 tools/affected.py` |
| whether a lint is worth speeding up at all | `python3 tools/prove-gates.py --list` |

Two standing facts worth knowing before proposing anything: the browser gates dominate the
full run, and the sweep's slowest suites are slow because they drive **real git** and a real
browser rather than fakes. That is the correct choice — a fake would encode the assumption
instead of the behaviour — so their cost is not a defect to remove.

## Checklist

- [ ] The claim about the cost came from running the subject, not from a grep or a guess
- [ ] Named which of the three numbers the change moves: wall clock, total CPU, critical path
- [ ] Confirmed the target is ON the critical path, or said explicitly that only CPU moves
- [ ] Ranked by shape, with coupling reported beside it rather than added into it
- [ ] Read the top-ranked file before trusting its score
- [ ] Reported what the change returned AND what the same pass spent
- [ ] A deferral names its number and the trigger that would reopen it
- [ ] Re-measured after the change with the same command as before it

Related: **no-silent-pass** for proving a check can fail before trusting it — including a
verification whose shortcut made it circular, which is how the declined optimization above
went wrong twice.
