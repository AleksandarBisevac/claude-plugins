---
name: before-you-claim
description: Seven questions answered with evidence at the moment a change is written, one for each defect class this repo's fault register keeps recording — a sentence claiming what the code does not do, a check that cannot fail, a fix for the instance while the class stays open, a rule that lives in prose with no mechanism, a property measured once, a guard that reads a command's spelling instead of its operation, a number written into prose. Use this skill every time you add or edit a comment, a docstring, a `.md` document, a `--help` text, a `--selftest` case, a lint, a hook, a guard, an agent brief, `orchestrator.md`, or any rule addressed to an agent; every time you fix a fault from the register or a bug from the manifest; and every time you are about to write down a number, a timing, or "does not reproduce". It applies to the ordinary edit, not only the big one — the register's worst recurrences were one-line comments and one-word fixes. The answers end whatever you hand over — the commit message, or when there is no commit, the notes, the PR text, the message back to the orchestrator — as a `claims:` block; a hook in this repo refuses a commit on these surfaces without one.
---

# Before you claim

Every defect class below was written by an agent that had read the rules and was following
them; the moment of writing had no question. This skill is the question — seven of them, each
answered with something that can be *shown*. It holds no rule of its own: `no-silent-pass`,
`writing-python` and `CLAUDE.md` say how; this asks *did you, on this change, and where is the
evidence?* Measured on this repo, a careful agent already does most of it unasked; what it does
not do without being asked is write the evidence down where a reviewer reads it (the block),
sweep the bare shape before narrowing (question 3), and say in a rule's own sentence whether
anything enforces it (question 4). Those three are where this skill earns its cost.

## Two touches

**Before the first edit**, one line: which questions this change will have to answer
(`touches: 1, 3, 4`). The sweep, the mutation and the second measurement are cheap before the
edit and expensive after; naming the question is what gets them done while they are cheap.

**Before you say done**, the `claims:` block (shape at the end) — one line per question, each
carrying the evidence you gathered or `n/a — <reason>`. It ends whatever leaves your hands: the
commit message when you commit; otherwise your notes, the PR description, or the message back
to the orchestrator. There is no "done except the block". A line that asserts where evidence
should be ("yes, it fails", no red output shown) is the skill not being used.

## The seven questions

1. **What does this sentence claim the code does — and where is the line that does it?**
   For every comment, docstring, `.md` sentence, `--help` text or brief instruction that
   describes behaviour: the `file:line`, or the sentence rewritten to say only what the code
   does. `scripts/claim-lines.py <diff> --tree <checkout>` lists every added prose block with a
   verb of behaviour, read off the file, so a paragraph added inside a docstring counts.

2. **What breaks this check, and did I watch it break?** For every case, guard, lint, hook
   branch: the mutation applied, the red output, the restore; for a guard, the over-fire
   mutation too, with the allow case going red. Purge `__pycache__` between cycles. "The suite
   is green" is not an answer — it was green before the case existed.

3. **Is this the fix for the instance, or for the class — and where else does the class live?**
   For every fix of a reported defect: before editing, grep the **bare** shape — the word, the
   number, the token — in the same file first, then the tree, and narrow only after you have
   seen every hit; a grep narrowed by the words you expect beside it (`seventeen` filtered by
   `edge|debt`) never shows the sentence about something else carrying the same rot. Paste the
   grep and its hits verbatim; then account for **every hit**: fixed, or *left, because …*.
   A sweep that names none of what it left is half a sweep — the next reader cannot tell a site
   you judged from one you missed.

4. **Does this rule live in prose, or in a mechanism?** For every `must`/`never`/`always`
   addressed to an agent — in `orchestrator.md`, a brief, a comment: the hook, script, schema
   or lint that enforces it, named **in the rule's own sentence**; and if nothing does, the rule
   says so about itself, where its reader will see it — *"Nothing enforces this today; the
   orchestrator's own recorded run is the verdict either way."* Saying it only in your notes is
   not enough: the notes are read once by one person, the brief by every agent it is handed to.

5. **Did I measure this once, and could the window have lied?** For every timing, "idempotent",
   "does not reproduce", saving: two runs with a deliberate gap, on the tree the claim is about,
   the spread written — or *measured once* beside the number, in the document.

6. **Does this guard read what the command will *do*, or what it *says*?** For every guard,
   matcher, allow/deny rule: the decision from the operation — the file set, the tool's
   semantics, the resolved path — never a pattern over the text or one tool's name; and the
   allow case proven quiet *before* the deny widens.

7. **Is this number derived by something, or written by me?** For every digit or spelled-out
   number in prose: the command that re-derives it beside it, or the number deleted and the
   pointer kept. History with a date stays legal.

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
4 <enforced by <hook/script>, named in the rule | rule says "unenforced because …" about itself | n/a — no rule to an agent>
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
