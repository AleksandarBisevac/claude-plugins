# The seven questions, long form

Each entry: the class as the register records it, what it looks like when it is written, what
the answer looks like, and examples from this repository — one of the class being written and
one of it being avoided. The examples are described by shape, not by fault id, because a fault
id points at a private register and this file is published with the code.

## 1. The sentence and the line

**The class.** A comment, docstring, document sentence, `--help` string, or brief instruction that
describes a mechanism the code does not have — because it never did, because it was reversed, or
because the code moved and the sentence stayed. The largest class in the register by a wide
margin, and the one whose instances look least like defects: the sentence is usually *nearly*
true.

**How it gets written.** The author knows what the code is *for* and writes that. "Each row is
chained like a journal row." "The guard refuses any read of a dotenv file." "Step 4 re-gates on a
quiet tree." Each was a true intention and a false description.

**What the answer is.** For each such sentence, the `file:line` where the behaviour lives. If you
cannot point at one, the sentence changes: either to what the code does today, or to an intention
marked as one. A description of a *mechanism* that names no mechanism is the shape to look for.

**Written, in this repo:** an evidence-ledger docstring that read as parallel to the journal's
tamper-evidence while the evidence row carried no hash at all; an orchestrator paragraph promising
a re-gate "on a quiet tree" two hundred lines above the step that fires while siblings are still
editing; a lock CLI's docstring saying it coordinates "clones of one machine" when the lock
directory resolves per clone.

**Avoided, in this repo:** `SECURITY.md`'s fail-mode table names `hooks/hooks.json` as the
authority and ships the command that prints the wiring, so the table can be compared to the
thing it describes — and since the second-attempt analysis, a gate does compare them.

**The script.** `scripts/claim-lines.py` reads a unified diff and lists every added or changed
line inside a comment, docstring or Markdown paragraph that carries a verb of behaviour
(`refuses`, `records`, `enforces`, `checks`, `never`, `always`, `guarantees`, `is chained`,
`serialises`, `blocks`, `denies`, `writes`, `reads`, `validates` …). It is a list to answer, not
a verdict — it cannot know whether the claim is true, only that it was made.

## 2. The check and the mutation

**The class.** A case, guard, lint or hook branch that cannot fail: a dead conjunct, a seam never
wired, a fixture that satisfies the rule two ways so deleting either alternative keeps it green,
an assertion over a set where a count was meant, a case that raises instead of failing and takes
every later case down unnamed.

**How it gets written.** The author writes the assertion the case is *about* and runs the suite.
The suite is green. Nothing distinguishes "green because the check holds" from "green because the
check reaches nothing".

**What the answer is.** The mutation applied to the thing the check guards — shown; the check's
red output — shown; the restore — shown. Where the check is a guard with an allow case, the
second mutation: weaken the guard until it over-fires, and show the allow case going red. Both
directions, because a guard that only ever proved it fires is a guard nobody proved stays quiet.
Purge bytecode caches between cycles; assert the mutation landed before believing a verdict.

**Written, in this repo:** a case labelled "observed from within the step" whose seam was passed to
a different function, so its observation list was empty and its assertion never mentioned it — all
four conjuncts held under the exact mutation it existed for. A case whose two conjuncts were both
dead: the first raised before the block the case was named for, the second listed the wrong
directory. A TAP fixture carrying both the opening plan line and the closing tally, so deleting
either alternative in the parser left the case green.

**Avoided, in this repo:** `tools/prove-gates.py` — every load-bearing lint has a row that breaks
the thing it guards and a row that weakens the guard, and a lint added without a row fails the
sweep. `tools/redfirst.sh` for one check by hand.

## 3. The instance and the class

**The class.** A repair that edits the site that was reported and leaves the sites that were not.
The register's recurrence chains are this: the same denominator rotting in the same file four
times because each fix touched the reported line; a guard "closed" eleven times because each
closure added the reported spelling.

**How it gets written.** The report names an instance; the fix fixes the instance; the fix is
honest and tested and the class is untouched.

**What the answer is.** Before the fix, the *shape* — expressed as a grep the instance is one hit
of — run across the tree, with its hits listed. Each hit fixed, or named as deliberately left with
the reason. The fix's description names the shape, not the instance.

**Written, in this repo:** "the `KNOWN_LAYER_DEBT` count rotted" fixed in two sentences, with five
more spellings of the same denominator sitting in the same file, found a month later. A merge
data-loss repair that closed the door it was reported through — a stale side — and left three
more: a row typed into a conflicted file, a concurrent append between grading and writing, a
torn row in the target.

**Avoided, in this repo:** the `--gate-clear` fault, found on one verb and then on two more, was
finally named at its structural cause — one `argparse` parser serving five verbs — rather than
patched a fourth time.

## 4. The rule and the mechanism

**The class.** A sentence addressed to an agent — `must`, `never`, `always`, `do not` — that no
hook, script, schema or lint enforces. The orchestrator document holds ninety-seven of them.

**How it gets written.** Something went wrong; the author adds the rule that would have prevented
it; the rule is correct; the next agent under load does not remember it.

**What the answer is.** The mechanism that enforces the rule, named beside it. If there is none —
and sometimes there cannot be — the rule says so about itself, so the reader knows it is trust and
not a gate. What is not acceptable is a rule that reads as enforced and is not.

**Written, in this repo:** "the executor must not run the gate" — the largest measured saving of
two field waves — survived only in an operator's handoff note, while the executor definition and
the orchestrator both said the opposite. "Stage the task's files … stage the journal directory …"
— five prose sentences for the one commit that happens most often, read as `git add docs/audit/`,
four scope breaches. "Never read secrets — enforced by the plugin's guard hooks" — with no way to
tell whether the guard was running.

**Avoided, in this repo:** `tools/check-prohibitions.py` — every bolded `NEVER` naming a command in
the orchestrator document is either enforced by a hook that is *driven* on every run, or declared
advisory with a reason that is itself checked. A rule that stops being enforced turns the gate red
by name.

## 5. The measurement and the window

**The class.** A property recorded from one observation: a timing, an idempotence, a "does not
reproduce", a saving, a count — true of the window it was taken in and recorded as true in
general.

**How it gets written.** The author runs it, sees the result, writes it down. The result was
real. The window was not the world.

**What the answer is.** Two runs with a deliberate gap — across a second boundary for anything
stamped to the second — on the tree the claim is about, not a copy under different load; the
spread shown, not one number. Where only one run is possible, the number carries *measured once*
beside it.

**Written, in this repo:** "the re-run is idempotent" — both runs inside one second, the marker's
timestamp identical by coincidence; with a 1.3 s gap the re-run was refused and two cases built on
the claim were timing-flaky. "−31%" — a scratch copy under agent load; −0.8 s on the live tree.
"Does not reproduce" — true of the checkout, false of the installed copy the reporter ran.

**Avoided, in this repo:** the performance report for 2.3.0 — every timing at least twice, spread
shown, the MEASURED and MECHANISM columns kept apart so a reader cannot carry an argued saving into
a sentence about speed.

## 6. The guard and the operation

**The class.** A guard that decides from the *text* of a command or a tool name — a filename
token, an interpreter flag, a heredoc marker, an extension list, a tool-name prefix — rather than
from what the operation will touch.

**How it gets written.** A report names a command; the guard learns that spelling; the next report
names another. The guard grows a list and never grows a model of the operation.

**What the answer is.** The decision made from the resolved operation: the file set a command will
read or write, the tool's semantics, the target path after resolution — and the allow case proven
quiet first, because a guard that fires on a legitimate read is switched off, and then guards
nothing.

**Written, in this repo:** the secrets guard matched `python -c` and was bypassed by a heredoc;
matched a dotenv name in the command and was bypassed by `grep -r`, a directory `Grep`, `diff`, a
glob loop, `xargs`; the write guards matched `Edit|Write` and were bypassed by an MCP file tool;
the shell-write gate matched source extensions and let `.json` — the plan itself — through.
Eleven closures, each a spelling.

**Avoided, in this repo:** `_scoped_commit.py` — a commit helper that stages explicit paths and
then *reads back* `git diff --cached --name-only`, refusing anything outside the allow-list. It
grades what is staged, not what was asked.

## 7. The number and its derivation

**The class.** A cardinality, duration, byte count, percentage or ratio written into prose in the
present tense, with nothing that re-derives it.

**How it gets written.** The number is true and useful the day it is typed. The lint knows some
shapes and deliberately not others — the author-enforced half is the half that recurs.

**What the answer is.** The command that re-derives the number, beside it — the basis may sit on
the next line, because prose wraps — or the number deleted and the pointer kept. History with a
date stays legal.

**Written, in this repo:** "seventeen `KNOWN_LAYER_DEBT` edges" in five sentences while the table
held one entry — the fourth recurrence of one number in one file. "~70 pins" that was roughly the
CSS subtotal presented as the total, and its correction wrong too.

**Avoided, in this repo:** `CLAUDE.md`'s front-end section, which once carried six figures and now
carries none — the command that prints them stays, and the section says why the numbers are gone.

## The two rules about the register

**A finding goes to the register before the fix.** A bug written into a session note is a bug no
gate reads; a release once went out over one. Record it, then fix it in its own change — and in the
code, cite the constraint, never the id. Four hundred and forty-seven comment lines in this
plugin's own code once pointed at a register its readers cannot open.

**A wrong diagnosis is corrected in place, never erased.** The register's value is that a later
author can see what an earlier one believed and why it was wrong. A first diagnosis that
prescribed removing a safety mechanism, a property recorded from one observation — both are still
there, with the sentence that says they were wrong. That is what stops the next author from
believing the same window.
