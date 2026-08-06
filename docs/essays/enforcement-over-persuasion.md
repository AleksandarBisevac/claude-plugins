# Enforcement over persuasion

*On the difference between telling an agent what to do and making it so — and on
the ways that distinction fails when you take it too far.*

---

## The claim

A prompt is a request. A hook is a constraint. Most of what is written about
steering coding agents is about writing better requests: sharper instructions,
firmer rules files, more emphatic capitals. That work is real and it helps. It is
also, structurally, persuasion — and persuasion has a failure mode that no amount
of rewriting removes. The model can simply not do it.

There is a single question that sorts one from the other:

> **What happens when the model does not comply?**

If the answer is "the instructions say not to," that is persuasion. If the answer
is "the tool call is denied, the agent is told why, and the edit never reaches
the disk," that is enforcement. The gap between those two answers is what this
plugin is for.

This is not an argument that persuasion is worthless. Most of an agent's
behaviour will always come from what it is asked. It is an argument that the
handful of things you actually cannot tolerate — a leaked credential, an edit
nobody planned, a review that never happened — should not be in the persuasion
pile.

## What enforcement means in practice

Three mechanisms, in descending order of how hard they are to argue with.

**1. The tool-call boundary.** The guard hooks run as `PreToolUse` handlers. A
`Read` of `.env`, a `sed -i` into a source file nobody planned to touch, a
`console.log` of a token — the hook returns a deny decision and the call does not
happen. There is no step where the model's cooperation is required, because the
model is not the thing being asked.

**2. The harness, not the prompt.** `audit-explorer` is a read-only agent. Not
because its system prompt asks it to be careful — because its frontmatter lists
no `Edit`, no `Write`, no `Bash`. The capability is absent from the harness. An
agent cannot be talked into a tool it does not have, and it cannot forget a
restriction that was never a restriction, only an absence.

**3. Structure that revalidates.** The manifest is the source of truth, and every
command that mutates it re-runs a referential validator afterwards — unique ids,
dependency cycles, reciprocal bug↔task links. Not "the command should keep the
manifest consistent." The command *cannot leave it inconsistent and exit clean*.

## The version of this that bites you

Here is the part usually left out of essays like this one, because it is the part
where the author was wrong.

The plugin enforces that every Python file under `hooks/` and `scripts/` carries
a `--selftest`. For most of its life, CI enforced this by running a
hand-maintained list of files. The list drifted three ways at once: nineteen
files on disk, ten named in `CONTRIBUTING.md`, fourteen in the build guide. The
drift was not cosmetic — one script's nineteen test cases had *never been run by
CI at all*.

The reason is exactly the thesis, turned around. **Adding a file and adding a
line to a list are two separate acts, and only one of them was enforced.** A rule
that depends on someone remembering to also do the other thing is not a rule; it
is a note. The fix was to replace the list with a glob, so a new file without a
selftest fails the step — the failure mode a list can never catch, because a list
does not know what it is missing.

Every persuasion-shaped rule in your own repository looks exactly like that list
until the day it doesn't.

## Where enforcement goes wrong: certainty without evidence

The opposite failure is more seductive, and this project shipped it for months.

The plan gate denies edits to files no in-progress task covers. In a repo with no
manifest there is no plan, so the gate fell back to a heuristic — allow one small
file per session, then deny. Read that again: it was issuing its *strongest*
verdict in the situation where it knew the *least*. Someone who installed the
plugin to look at it, ran no setup, and tried to edit a file was denied by a
policy that did not exist.

That was enforcement as bluff. And it made the plugin's own worst outcome — being
uninstalled in irritation — the most likely one, because the cheapest exit from a
gate you did not ask for is to remove the gate.

The deny message made it worse by naming the wrong exit. It suggested a bypass
keyword. **A guard whose cheapest escape route is a bypass keyword is training
people to reach for the bypass keyword** — which is the same as having no guard,
with extra steps and more resentment.

So the gate is now graded on the evidence it has: it observes with no manifest,
warns with a manifest but no phase running, denies once a phase is `in_progress`,
and `enforce: true` restores always-on deny for repos that want it. Not a
softening. The same principle, applied to the one surface that had been exempt
from it.

One category stayed ungraded, deliberately. **No secret guard is conditional.**
Reading `.env` is wrong whether or not a plan exists, so those guards need no
evidence to be correct. The grading is about claims that depend on context, not
about weakening whatever is inconvenient.

## The narrower version of the same mistake

The plugin's own doctor once failed a build by reporting `runner not on PATH:
plugin-validate (claude)`. The observation was true — that CI job deliberately
does not install the Claude CLI. The *severity* was false. Every other finding it
raises is a defect in the **repository**: an invalid manifest, a malformed
config, broken shards. A tool that is not installed is a gap in **this machine**.

Failing a build over an accurate statement is its own kind of unearned
enforcement, and it produces precisely one behaviour in the people who hit it:
they stop reading the output. A doctor that cries wolf is worse than one that
admits a limit.

## What it cannot do, stated plainly

Every guard here inspects the *text* of a tool call, and text inspection is
bypassable in principle. These are guardrails against an agent making a mistake.
They are not a sandbox against a determined adversary, model or human. For hard
guarantees you want OS-level sandboxing and the harness's own permission modes;
these hooks are the cheap, always-on first line underneath those.

[`SECURITY.md`](../../SECURITY.md) enumerates seven accepted bypass classes in
detail — full Bash-write coverage is statically undecidable, subagents do not
inherit parent hooks in every version, test files are exempt from plan-first so
TDD stays frictionless, the secret-read guard is name-based and cannot see a
secret in an unconventionally-named file, and so on. Each one is listed with what
compensates for it.

That document is not an appendix to this argument. It *is* the argument. **An
enforcement claim published without its limits is just persuasion wearing a
lab coat** — and a reader who discovers the seventh bypass class on their own,
after trusting the first six, has learned something worse about the tool than the
bypass itself.

## The general form

Once you have been burned by a gate that denied on no evidence, the rule
generalises past gates entirely, and it is the rule this repository now applies
everywhere:

> **Every claim carries the condition that makes it true, or it does not get
> made.**

- The routing advisory will name a cheaper model — but stays **silent** when it
  has too little in-repo evidence, when the cheaper model needed more retries, or
  when the saving is below an absolute floor. A price list is not a finding.
- The cost projection is a p25–p75 **range**, never a point estimate, and it is
  suppressed entirely below a sample gate. Cost bands are computed from the
  project's own median and p90, and `band_of` returns nothing while suppressed,
  so no caller can render a band that was never computed.
- The report's cache section reports a hit rate and refuses to state a dollar
  saving, because that number would have to be invented.
- The "ready now" list folds at twelve items and states the true count, because a
  silent cap reads as *that is all of them* — the worst failure a to-do list can
  have.
- The skills added for discoverability carry an explicit **do not use this for**,
  pointing one-shot diff review back at `/review`. A skill without a negative
  condition is a claim without one.
- Even the version number is a claim. A release that added two features cannot
  ship as a patch bump, because the number asserts something about what changed.

None of these are about security. They are the same discipline at different
scales: a statement that cannot be checked is a statement that should not be
printed, and a rule that depends on someone remembering it is not a rule.

## Why this is the harder sell

Enforcement is worse than persuasion at demos. It says no. It says no at the
moment you were trying to show someone how smooth the tool is, and the reason it
says no is usually that you skipped a step on purpose.

The case for it is not that it feels good. It is that the alternative degrades
silently. A rules file that the model followed nine times out of ten looks
identical, in every log you will read, to one it followed ten times out of ten.
You find out which one you had when something reaches production.

The gate that stops you is the only one you can prove was working.

---

*Assembled from `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md` and the plugin
README of [`audit@quality-gates`](https://github.com/AleksandarBisevac/claude-plugins).
Every failure described here is one this repository shipped and then fixed; the
commit for each is in the changelog under the version named.*
