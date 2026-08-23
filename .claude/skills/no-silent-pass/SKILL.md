---
name: no-silent-pass
description: Write Python whose failures are visible and checks that actually fire — distinct sentinels for success and error, filters that narrow to nothing without reading as "all clear", output never discarded on a non-zero exit, and selftest cases proven red before they are trusted (mutate the fix, mutate it the other way too, count occurrences rather than asserting presence, pick fixture values that tell the two versions apart). Use when adding or reviewing a `--selftest` case, when a guard or lint is added, when a function reduces observations to a number a threshold reads, when a bug is fixed and a regression case is written, or when a check has only ever been seen passing.
---

# No silent pass

Two halves of one rule. Code must not produce normal-looking output when something went wrong,
and a check must not look green while asserting nothing. Both fail the same way: everything
reports fine and nobody learns anything for months.

This repo's test suite is the `--selftest` block inside each file, printing `N/M cases passed`.
Everything below is about those cases and the code they guard.

## Fail loud

- **Give success and failure distinct sentinels.** If the error path writes the same value the
  success path writes, failed runs read as complete. `except Exception: status = "READY"` is the
  shape to look for.
- **When you catch, either recover meaningfully or make the failure visible** — raise, or return
  a distinguishable value. A `return`/`continue`/fallback inside `except` that produces
  normal-shaped output is where silent corruption lives.
- **`x = x or default` is a bug whenever `0`, `False` or `""` are meaningful.** Use
  `x if x is not None else default`. Reserve the `or` form for empty containers.
- **A no-op on unexpected input is silent corruption.** Skipping a key you do not recognise, or
  `continue`-ing past a record you cannot parse, with no error and no count, leaves the caller
  believing the operation applied.
- **Filtering down to empty must never read as "all clear."** When a selector, rule set or work
  list narrows to nothing, an "evaluated everything, found no problems" path reports a perfect
  result while checking nothing. Say that the set was empty.
- **Validate every precondition before the first mutation.** A write that half-applies and then
  raises leaves the caller's state corrupted even though the exception was correct. Where that is
  not possible, stage on a copy and commit after.
- **Do not discard the real output on a non-zero exit.** A runner that returns only stderr when
  `returncode != 0` loses the answer for tools that exit non-zero *by design* and write their
  result to stdout — which is exactly what this repo's own validators and gates do.
- **Impose a total order before serializing.** Iterating a `set` emits a different order per
  process, so a regenerated file is the same data reshuffled and the real change drowns in noise.

## A check you enabled is not a check that fires

Before relying on a lint, guard or assertion to protect something, **write the violation on
purpose once and confirm it is reported**. A rule that is configured, green, and silently
exempted is worse than no rule, because it is believed.

This is the same discipline the repo already applies to its lints — they are shown red before
being trusted. Extend it to every new one.

**An exemption carries a premise. Check the premise, not just whether the exemption still
fires.** A rule here forbade dividing by a `||1` denominator and carved out one field, "where
one attempt is the true default". The carve-out worked exactly as written for a long time, and
the premise was false: the orchestrator writes `attempts: 0` for every new task, and two
documented paths take a count back down while the spend stays attributed. So the field's zero
was a recorded value, and `||1` reported one attempt for a task the plan says has none — which
is what the rule's own next sentence forbids ("in any other position it manufactures an answer
to a question that has none"). A silently disabled rule is the loud version of this. The quiet
version is an exemption that fires correctly for a reason that stopped being true, and the way
to find it is to read the reason and try to measure it.

**A shortcut in a verification can make it circular.** Confirming a cache "does not lie" means
comparing the cached answer against an *independently* computed one, which costs two
computations. Seeding the cache from the same value the case compares it against saves one —
and turns the assertion into a value compared with itself, which cannot fail. That was done
here to save under a second, in the block whose entire subject is a check that must be able to
go red. Two computations is the floor, not an oversight; when a verification looks
suspiciously cheap, work out which two things it is comparing and whether they came from
different places.

## Prove the case can fail

Every regression case makes an implicit claim: *this would have caught the bug.* The only way to
check the claim is to put the bug back and watch the case go red. Do it while the fix is fresh.

**Know what red looks like for the mutation you chose.** A reintroduced bug does not always
surface as a clean assertion failure:

- remove an iteration or retry cap and the suite **hangs** instead of failing — run it under an
  external timeout, and no output within N seconds *is* the reproduction;
- if the mutated run dies before the cases execute, nothing ran and you have learned nothing.

## Mutate in both directions

A fix that adds a conditional — a warning on incomplete data, a validation check, a flag that
suppresses a claim — has **two** wrong implementations, not one: it never fires (the original
bug), or it always fires. The case you naturally write covers only the first.

The case that catches the second **looks vacuous and gets cut in review**: it asserts that a
fully successful run emits *no* warning, which passes on the pre-fix code by construction. It is
the only case that fails when the guard becomes unconditional. Keep it, and say in a comment
which mutation it is there for.

## Count, do not merely find

`assert X in output` proves that *at least one* X exists. It cannot tell you there are two, or
which one a consumer will honour — which is the exact shape of bugs in generated output, where a
base template and an override each emit one and they disagree. Extract every occurrence and
compare the whole list.

This repo has already been bitten by it: report probes once grepped the whole document, embedded
`report.js` included, so a markup literal inside a JS string could move a count. The fix was to
judge over the markup with `<script>` blocks stripped. Presence assertions still outnumber
counting assertions in the report's suite roughly four to one, so prefer counting whenever the
thing being asserted could legitimately appear more than once.

Assert the escaped form is **present**, not only that the dangerous form is absent — otherwise a
filter that silently deletes the whole field passes.

## A lint that reads text will read yours

Several guards here scan source as TEXT rather than as code: `_refs` looks for a `.py` basename
anywhere under `tools/`, `_output.prose_number_claims()` and `_deps.doc_prose_numbers()` look for a
cardinality in prose, `_ui_theme` looks for an undeclared `var(--…)`, and the shared layer forbids
naming a scheme it must not depend on. **None of them can tell your code from your comment about
your code**, and the usual way to meet one is to explain it — the explanation contains the shape.

**The two prose scanners read EVERY `.py` and EVERY `.md` this repo keeps**, this file included, so
`tools/`, `plugins/audit/tests/` and the plugin's own product documents are all inside them now.
There is no directory left where a shape can be spelled out safely; the way out is a row in
`_output.PROSE_SCAN_EXEMPT` with a reason, and there are very few of those.

It has happened repeatedly, and the list is the argument rather than the count of it:
`path.join(SCRIPTS, …)` written in a comment, a `var(--viz-N)` inside a JSDoc, the four letters of
a scheme in a sentence saying the panel is served over one, a lint whose own comment and own
fixture failed the lint, and — twice in one edit — a test field abbreviated to the two letters of
the Python extension, first in the code and then in the comment added to explain why the code had
been renamed.

**The one that could not be reworded, and what to do instead.** When the prose scan widened past
`scripts/`, every false positive it produced was the same thing: the `<passed>/<total>` tally each
suite prints, appearing as a fixture, as a regex and as an ASSERTED literal in the sweep runner,
the harness and half a dozen suites. Those bytes are the contract CI greps for, so rewording them
was not available and neither was loosening the shape. What fixed it was **narrowing on a real
distinction** — a numeral written with an interior separator is a ratio or a measurement, and
neither is a count of things — plus building the literal wherever the fixture merely needed to
contain one. A narrowing you can name and pin is legitimate; a widening that admits your prose is
not, and the two are easy to confuse when you are the one being flagged.

Every one of those firings was **correct**. The pattern to learn is not "the pattern is too broad";
it is:

- **Repair by rewording, not by widening.** A pattern loosened to admit your prose stops catching
  the thing it exists for, and you will not notice, because the case that would have caught it is
  the one you just changed.
- **Describe the shape without spelling it.** "a field abbreviated to the two letters of the Python
  extension" survives the scanner; the literal does not.
- **Build a forbidden literal rather than writing it**, when a fixture genuinely needs one.
- **Re-run the lint after writing the comment**, not only after writing the code. The second firing
  above cost a full cycle purely because the comment was assumed to be inert.

## Pick fixture values that separate the bug from the fix

A case survives mutation most often because its *data* cannot tell the two implementations apart.
Before writing the assertion, work out what the buggy version would produce from your fixture. If
it produces the same value, the fixture is the problem — change it, not the assertion.

**A hand-written fixture is itself a mutation of reality.** When the same person writes both a
parser and every fixture it is tested against, both encode the same assumption and the suite is
green against a guard that cannot fire in production. Capture at least one sample from the real
source and point the case at that.

## Ambient state

Pin every variable that feeds a lookup, not just the one you know about. Setting `HOME` looks
sufficient for config-directory resolution, but the XDG variables are set independently on Linux,
so the lookup ignores your temp directory and every case shares one real config directory.

This matters here specifically: CI runs the suites on **ubuntu and windows**, and a case that is
incomplete on one platform is untested on exactly the platform that found the last several bugs.
The same applies to encoding — the suites are re-run under `PYTHONIOENCODING=cp1252` for this
reason.

## Checklist

- [ ] Error paths write a value the success path never writes
- [ ] No `except` returns normal-shaped output without saying something failed
- [ ] `or default` only where an empty container is the sole falsy case meant
- [ ] An empty filter result is reported as empty, never as "nothing wrong"
- [ ] Preconditions validated before the first mutation, or staged on a copy
- [ ] Non-zero exits keep stdout; sets are sorted before serializing
- [ ] Every new lint or guard was shown red once, on purpose
- [ ] Every regression case was proven red by restoring the bug
- [ ] Conditional fixes carry the second-direction case, with a comment saying so
- [ ] Occurrences counted, not just found, wherever more than one could appear
- [ ] Fixture values chosen so the buggy and fixed versions disagree
- [ ] Every variable feeding a lookup pinned, on both CI platforms

Related: **verifying-external-behavior** for confirming what a remote system actually does before
asserting it, and **running-resumable-sync-jobs** for exit codes and partial-failure reporting.
