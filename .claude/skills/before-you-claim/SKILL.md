---
name: before-you-claim
description: Seven questions answered with evidence at the moment a change is written, one for each defect class this repo's fault register keeps recording — a sentence claiming what the code does not do, a check that cannot fail, a fix for the instance while the class stays open, a rule that lives in prose with no mechanism, a property measured once, a guard that reads a command's spelling instead of its operation, a number written into prose. Use this skill every time you add or edit a comment, a docstring, a `.md` document, a `--help` text, a `--selftest` case, a lint, a hook, a guard, an agent brief, `orchestrator.md`, or any rule addressed to an agent; every time you fix a fault from the register or a bug from the manifest; and every time you are about to write down a number, a timing, or "does not reproduce". It applies to the ordinary edit, not only the big one — the register's worst recurrences were one-line comments and one-word fixes. The answers end whatever you hand over — the commit message, or when there is no commit, the notes, the PR text, the message back to the orchestrator — as a `claims:` block; a hook in this repo refuses a commit on these surfaces without one.
---

# Before you claim

Every defect class below was written by an agent that had read the rules and was following
them; the moment of writing had no question. This skill is the question — seven of them, each
answered with something that can be *shown*. It holds no rule of its own: `no-silent-pass`,
`writing-python` and `CLAUDE.md` say how; this asks *did you, on this change, and where is the
evidence?*

**Questions 1, 2, 5 and 7 are one line each because the evals said so.** Run against a baseline
with no skill on 2026-09-12, twice and on two models, the arms tied on those four at full marks
and separated on question 4 both times. They still get asked; they no longer get a paragraph.
The runs and their grading are in `../before-you-claim-workspace/iteration-4/benchmark.json`.

## Two touches

**Before the first edit**, one line: which questions this change will have to answer
(`touches: 1, 3, 4`). The sweep, the mutation and the second measurement are cheap before the
edit and expensive after; naming the question is what gets them done while they are cheap.

**Before you say done**, the `claims:` block (shape at the end) — one line per question, each
carrying the evidence you gathered or `n/a — <reason>`. It ends whatever leaves your hands: the
commit message when you commit; otherwise your notes, the PR description, or the message back
to the orchestrator. There is no "done except the block". A line that asserts where evidence
should be ("yes, it fails", no red output shown) is the skill not being used.

The hook that asks for the block sees `git commit` only after `&&`, after `;`, or at the start
of the command — not one that begins its own line under a heredoc, and not `-F -`. Its silence
is not a verdict.

## The seven questions

**1. What does this sentence claim the code does — and where is the line that does it?** The
`file:line`, or the sentence rewritten to say only what the code does.
`scripts/claim-lines.py <diff> --tree <checkout>` lists the added prose that claims behaviour.

**2. What breaks this check, and did I watch it break?** The mutation, the red output, the
restore; for a guard, the over-fire mutation too, with the allow case going red. Purge
`__pycache__` between cycles. "The suite is green" is not an answer — it was green before the
case existed. `no-silent-pass` is the long form.

**3. Is this the fix for the instance, or for the class — and where else does the class live?**
Grep the **bare** shape — the word, the number, the token — in the same file first, then the
tree, and narrow only after you have seen every hit: a grep narrowed by the words you expect
beside it (`seventeen` filtered by `edge|debt`) never shows the sentence about something else
carrying the same rot. Paste the grep and its hits verbatim, then account for **every hit**:
fixed, or *left, because …*. A sweep that names none of what it left is half a sweep — the next
reader cannot tell a site you judged from one you missed.

**4. Does this rule live in prose, or in a mechanism?** For every `must`/`never`/`always`
addressed to an agent: the hook, script, schema or lint that enforces it, named **in the rule's
own sentence** — and if nothing does, the rule says so about itself, where its reader will see
it: *"Nothing enforces this today; the orchestrator's own recorded run is the verdict either
way."*

The failure has one shape, and it is the shape that costs marks: the author builds the
mechanism, puts it somewhere real — a drift lint, a README row, a test anchor — and never puts
the sentence where the rule's reader is, so the brief handed to the executor still says only
*never do this*. **The mechanism is not the answer; the sentence naming it, in the rule's own
text, is.** Your notes are read once by one person; the brief is read by every agent it is
handed to.

**5. Did I measure this once, and could the window have lied?** Two runs with a deliberate gap,
on the tree the claim is about, the spread written — or *measured once* beside the number, in
the document. Readings that agree inside one quiet window are still one window.

**6. Does this guard read what the command will *do*, or what it *says*?** The decision from the
operation — the file set, the tool's semantics, the resolved path — never a pattern over the
text or one tool's name; and the allow case proven quiet *before* the deny widens. This is the
register's longest-running class, and it recurs because a pattern over text always looks
finished: a commit guard that reads `&&` but not a newline, a history guard that refuses a
heredoc whose only act is to write a file. Both were widenings of an earlier text pattern. The
test is whether you can name the operation the decision reads.

**7. Is this number derived by something, or written by me?** The command that re-derives it
beside it, or the number deleted and the pointer kept. History with a date stays legal;
`CONTRIBUTING.md`'s *Writing a count that is allowed* is the long form. A green build is not
evidence — the lints cannot see a decimal, or tell a past-tense count from a present-tense one.

Two rules about the register: a finding goes into it *before* the fix, never inline in an
unrelated change, and the fix cites the constraint in the code, never the fault id; a wrong
first diagnosis is corrected in place with a sentence saying it was wrong, never deleted.

## The block

`claims:` alone on a line, then one line per question in order; a line may continue on
indented lines. The hook checks presence and shape; the reviewer judges the answers.

```
claims:
1 <file:line that does what the sentence says | rewritten to say only what the code does | n/a — no behaviour claimed>
2 <mutation → red output → restored; allow case → red under over-fire | n/a — no check touched>
3 <grep for the bare shape: N hits — each fixed, or left because … | n/a — not a fix of a reported defect>
4 <enforced by <hook/script>, named in the rule's own sentence | rule says "unenforced because …" about itself | n/a — no rule to an agent>
5 <two runs, gap, spread | "measured once" beside the number in the document | n/a — no property recorded>
6 <decision reads the operation, not the text; allow case proven quiet first | n/a — no guard>
7 <command beside the number | number deleted, pointer kept | n/a — no number written>
```

Filled in, from a real change (a guard taught to see an MCP read):

```
claims:
1 guard-secrets-read.py:1402-1414 is the branch the docstring describes; hooks.json:5 routes mcp__.* to it
2 branch removed → m1-m6 red (213/219) → restored 219/219; read-verb check dropped → m9, m10 (allow) red
3 grep -n 'tool == "' guard-secrets-read.py: 3 hits — Read, Grep, Bash, each already reading a resolved path; MCP joins them
4 n/a — no rule to an agent
5 n/a — no property recorded
6 decision = resolved `path`/`paths` against SECRET_PATH; allow: mcp read of README → no output, exit 0, shown before the deny widened
7 n/a — no number written
```

`references/questions.md` holds the long form of each question — why the class recurs, and
examples from this repo of it being written and of it being avoided.
