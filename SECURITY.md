# Security policy

The `audit` plugin ships enforcement hooks (secret-read blocking, plan-first
gating, token-logging bans). This document states exactly what those guards do
and do **not** guarantee, so you can decide what to rely on.

## Threat model: guardrails, not jails

The hooks are **deterministic guardrails against accidental agent misbehavior**
— an agent absent-mindedly `cat`-ing a `.env`, logging a token, or editing half
the repo without a plan. They are **not** a sandbox against a determined
adversary (model or human): every guard inspects tool-call *text*, and text
inspection is bypassable in principle. For hard guarantees use OS-level
sandboxing and Claude Code permission modes; use these hooks as the cheap,
always-on first line.

## Secrets: friction and evidence, not containment

The sentence above — *every guard inspects tool-call text* — has a consequence
for secrets specifically that this document used to leave for you to work out.
Stating it plainly:

**These hooks see intent, not I/O.** `guard-secrets-read` matches the text of a
tool call. It never observes a file being opened, a byte being read, or a value
reaching the transcript. So a secret that arrives **indirectly** is invisible to
it by construction, not by oversight:

```
$ direnv exec . printenv VERCEL_SCOPE     # .envrc holds `export VERCEL_SCOPE=…`
```

The command names no `.env` file — `direnv` reads it. The same holds for a test
runner that loads `dotenv`, a script that opens the file itself, and any process
that already has the value in its environment. Wrappers around `printenv`,
`.envrc` by name, `direnv dump`/`export`, `process.env` dumps and the
`dangerouslyDisableSandbox` combination below are all matched now; **the class is
not closed and cannot be**, because closing it would mean watching I/O, which a
`PreToolUse` hook does not do.

**Containment is the harness sandbox's job, and always was.** That is not a
regression and not a gap in this plugin — it is the boundary between what a hook
can do and what an OS-level sandbox can do. Claude Code's `sandbox` settings and
`permissions.deny` rules are the layer that actually stops a read. This plugin
leans on that layer; it does not replace it, and for a long time it never checked
whether the layer was there at all. `/audit:doctor` now attests it, and says so
when it cannot:

```bash
python3 plugins/audit/scripts/status/audit-doctor.py     # `sandbox` + `secret rules` rows
```

Because no environment variable carries sandbox state and the doctor is read-only,
its basis is the settings files alone. **"Not declared" is reported as *not
established*, never as *off*** — managed policy and a `--settings` flag outrank
every file it can read.

**So the ceiling here is friction plus evidence.** Friction: the obvious spellings
cost an extra step and a refusal the human sees. Evidence: a Bash
call carrying `dangerouslyDisableSandbox` — the documented per-call escape hatch,
which switches off the only layer that *can* contain a read — appends a
`bash.unsandboxed` row to the journal: a **digest** of the command, its byte
length, its program name, and the cwd relative to the repo. That stops
nothing; `PostToolUse` is after the fact. It makes the bypass **countable**, which
is the same bargain the audit trail strikes below: a smoke detector, not a vault.

Two ways this plugin refuses rather than records, for the narrow cases where
refusing is not merely theatre: the escape hatch combined with a command that
reaches the environment layer is denied outright, and the ordinary spellings
(`cat .env`, `printenv`, `source .envrc`, a `process.env` dump) are denied whether
or not a plan is running. **If your threat model includes a determined adversary
and real secrets, the load-bearing control is the sandbox and the deny rules — not
this plugin.**

## Fail modes (by design)

Every hook script launches through `hooks/py-launch.sh`, which resolves
`python3` → `python` → `py`. The fail mode when **no interpreter exists** is
hardcoded per hook in `hooks/hooks.json` — it cannot live in
`.claude/audit.config.json` because reading that config requires Python
(chicken-and-egg).

The table below is **per hook and event**, not per script and not per
registration: a script registered on several matchers of one event fails the same
way on each, while `require-plan` on `PreToolUse` (decide) and on `PostToolUse`
(commit that decision) fail differently, which is what the split is for. The
authority is `hooks/hooks.json`, and it prints the full wiring:

```bash
python3 -c "import json;d=json.load(open('plugins/audit/hooks/hooks.json'));[print(e,b.get('matcher','-'),h['command'].split()[-2].split('/')[-1]) for e,bs in d['hooks'].items() for b in bs for h in b['hooks']]"
```

This paragraph used to carry three counts — of scripts, of rows, and of "guard
hooks" — and two of them were wrong by the time anyone read this sentence. They
are gone rather than corrected, because a corrected number rots on the next
commit and the command above does not.

| Hook | Event | No interpreter | On internal error |
|---|---|---|---|
| `guard-secrets-read` | PreToolUse Read/Grep/Bash | **ask** (manual approval prompt, loud) | allow (fail-open) |
| `guard-edits` | PreToolUse edits | **ask** | allow |
| `guard-history-rewrite` | PreToolUse Bash | **ask** | allow |
| `require-plan` | PreToolUse edits | **ask** | allow |
| `guard-capabilities` | PreToolUse Skill/Task/Agent/MCP | **ask** | allow |
| `require-plan` (state commit) | PostToolUse edits | silent | no-op |
| `guard-bash-writes` | PostToolUse Bash + edits | silent | no-op |
| `remind-tdd` | PostToolUse edits | silent | no-op |
| `journal-writes` | PostToolUse edits + Bash | silent | no-op |
| `detect-plan-skip` | UserPromptSubmit | silent | no-op |
| `meter-usage` | Stop / SubagentStop / SessionEnd | silent | no-op |

### When the plan gate actually blocks (0.20.0)

The plan gate is **conditional**, and anyone reasoning about this plugin's guarantees needs
the condition. It denies only when there is a plan to enforce against: with no manifest it
records and reports without blocking, with a manifest but no phase `in_progress` it warns,
and it denies once a phase is running. `enforce: true` in `.claude/audit.config.json` denies
at every tier, and `planGate` (0.34.0) pins any single tier by hand — `"observe"`, `"warn"`,
`"ask"` (each out-of-plan edit waits for the human's approval) or `"deny"` — winning over
`enforce` when both are set; a `planGate` typo fails open to the graded ladder, never to
deny. Both plan gates are graded this way — `require-plan` and the shell-write
branch of `guard-secrets-read` — so the same file gets the same verdict whether it is edited
through a tool or through `sed -i`.

**No secret guard is graded.** Secret reads, the token-logging ban and the shell secret
checks deny by default at every tier, with or without a manifest: reading `.env` is wrong
regardless of whether a plan exists, so those guards need no evidence to be correct. If you
are relying on this plugin for secret containment, that behaviour is unchanged.

**Neither plan gate governs a path OUTSIDE the consuming repository, and it says which
rather than falling silent.** `_config.rel_path` is `os.path.relpath`, which answers a path
in another tree with a run of `..` segments — an ordinary-looking string that read as repo
source, so a helper script written to the system temp directory during a read-only command
was refused for plan coverage no manifest could ever have given it: a manifest names paths
in its own tree and nowhere else. `_config.within_root` is the containment test both gates
now ask first, and the verdict is an **allow that names the scope**. Out of scope is not
"unknown" — that is what the fail-open paths above are for — and a silent pass would be the
same verdict with the reason thrown away. Symlinks are resolved on both sides, because a
repo reached through one is the same repo; an unresolvable path answers *inside*, so an
error in the test can only leave a gate where it already was, never switch one off.
`remind-tdd` asks the same question for a reason worth stating separately: its nudge is a
CLAIM about a file rather than a decision about one, and it was also spending the session's
throttle on a tree it does not govern, which silenced the next reminder that was deserved.
This is the same posture `guard-bash-writes` already takes toward a command that ran in
another tree, and the practical consequence is the same: a session whose project directory
is one checkout does not gate edits into a *different* one, and opening the session in the
tree being edited is what restores coverage. That guard's *edit* branch asks the same
question now, and it is a retention rule rather than a gate: an out-of-tree Edit used to be
appended to its per-session `toolEdited` list under relpath's `../..` spelling, where no
`git status` line from the watched tree could ever equal it. Nothing read it and nothing
printed it, so there was no verdict to fix — the record went because a path outside the
consuming repository is not this plugin's to keep, on disk or in memory.

### The one denial that is not about the plan (0.27.0)

`require-plan` also refuses a write to the **manifest or a phase shard** when the
concurrency lock for that path is held by a **different, live session**. It is the plugin's
only decision keyed on session identity, so it is worth being exact about when it fires:

| Situation | Verdict |
|---|---|
| No lock file for that path | **allow** — taking a lock is honoured, not required |
| Lock has no `sessionId` (hand-written, or an older orchestrator) | **allow** — an unattributable lock must never be able to deny |
| The lock is this session's | **allow** — matched on the payload `session_id`, `$CLAUDE_CODE_SESSION_ID` **or** `$CLAUDE_PID`, because those are not all the same value (see below) |
| Another session, and its pid is **alive on this host** | **deny** |
| Another session, but its pid is **gone** | **allow**, with a PostToolUse notice that the lock is still there |
| No git repo, unreadable lock, `audit-lock.py` missing | **allow** |

**"This session" has more than one name, and that nearly broke it.** The lock is taken from
**Bash**, which reads `$CLAUDE_CODE_SESSION_ID`; the decision is made in a **hook**, which is
handed `session_id` in its payload. Measured in a live session those are different values, so a
run would have locked as one identity and then been refused as another — the gate denying the
orchestrator its own bookkeeping. A hook subprocess inherits the parent environment, so it
compares against all three ids and treats any match as its own lock. The tie goes to "ours":
matching too eagerly costs a missed denial, failing to match breaks the run.

It is scoped to `manifestPath` and `<manifest dir>/phases/*.json` and touches nothing else —
ordinary source files remain entirely the plan gate's business. The point is narrow: two live
sessions writing one shard in one working tree produce **no git conflict**, because git never
sees two versions, so the loser's bookkeeping silently overwrites the winner's. Everything
uncertain resolves to *allow*, in keeping with the fail-open posture above.

Through `sed -i` and friends the same write cannot be caught before it lands
(bypass class 1 below); `guard-bash-writes` reports it afterwards instead.

Both `_config.manifest_state` and `_config.plan_gate_mode` degrade to the **least** aggressive
verdict on any internal error, in keeping with the fail-open posture above: a crash in the
evidence check can only relax the gate, never manufacture a denial.

## What the usage ledger records

`meter-usage` reads the session transcript to recover token counts, which Claude
Code does not pass to hooks directly. It is worth being precise about what that
does and does not capture, because "the plugin reads your transcript" deserves a
straight answer:

- **Recorded**, to `.claude/usage/<YYYY-MM>.jsonl`: token counts per tier, the
  model id, an hour-resolution timestamp, the git branch, the repo directory name,
  the session/subagent ids, the resolved phase/task, and the author.
- **Never recorded**: prompt text, response text, thinking, tool inputs, tool
  results, file contents, or file paths. The ledger is counts and dimensions only.
- Transcripts are opened **read-only**; nothing is ever written back to them.
- The author defaults to `git config user.email`. Set `usage.authorMode` to
  `"hash"` for a pseudonymous but still groupable id, or `"none"` to drop author
  attribution entirely.
- The ledger is **gitignored by default** — it is local telemetry until a project
  decides otherwise.
- Set `usage.enabled: false` in `.claude/audit.config.json` to turn the whole thing
  off; the hooks then return immediately.
- The meter's **only** outputs are two `systemMessage`s, never a decision: one when
  the task in flight passes the project's outlier cost band (at most once per task
  per session), and one on `SessionEnd` summarising what the session cost. Both
  carry counts, task ids and a dollar figure — never anything read out of the
  transcript — and block nothing. Under `usage.showCost: false` the first states a
  multiple and the second omits the figure, so the setting is not defeated by
  either message.
- `/audit:panel`'s **Export report** button writes only to the report location
  derived from the project's own `manifestPath`, re-checked against the project
  root; there is no path parameter on the route to traverse with. The rendered
  file is served back through the panel's token-guarded origin.

## The audit trail: tamper-evident, not tamper-proof

Since 0.29.0 every edit-tool write to the manifest or to
`.claude/audit.config.json` appends a row to an append-only, hash-chained journal
(`scripts/governance/audit-journal.py`, written by the `journal-writes` hook and by the
panel's own saves). Each row carries who, when, what changed, a hash of the
document the write left behind, and the hash of the row before it.

One row is not about the plan at all: a Bash call carrying
`dangerouslyDisableSandbox` appends `bash.unsandboxed` with a **digest** of the
command, its byte length, its program name, and the cwd relative to the repo.
It is here because the same property is what makes it worth having — an
event nobody can prevent is at least one nobody can quietly deny, and this is
the file that makes denial expensive. Ordinary sandboxed Bash calls are not
recorded; the flag is what is read, so the journal cannot decay into a shell log.

The claim it makes is narrower than "an audit log", and the difference is the
point:

- **What `audit-journal.py verify` detects.** A row **edited** after it was
  written (it no longer hashes to its own contents), a row **deleted** or
  **reordered** (the chain breaks at that point), a file **renamed** into another
  writer's slot (the first row's anchor is derived from the file's own name), a
  **torn tail** from an interrupted write, and **out-of-band drift** — a manifest
  or config that changed with no row to explain it.
- **What it cannot detect.** A forger who rewrites the *whole* file, recomputing
  every hash forward, produces a chain that verifies. There is no way around this:
  a tamper-**proof** log needs a secret the tamperer cannot read, and there is
  nowhere on a user's own machine to keep one from that same user. Deleting the
  journal, or a file of it, is the same class of act — and deliberately loud
  rather than silent: `verify` sees the rows go missing and the file's history is
  in git.
- **What it never sees.** The CONTENT of a shell write. `sed -i` and `>` do not
  reach an edit-tool matcher, so no row says what they changed — they surface
  instead as out-of-band drift, and `guard-bash-writes` reports a shell write
  *into the journal directory* after the fact. (A `bash.unsandboxed` row records
  that an unsandboxed command RAN — and not even the command itself, only a
  digest of it; never what it wrote.) Anything written while
  the plugin is disabled is invisible for the same reason every other guard is:
  the user's own switch outranks it.
- **What it records.** The same shape as the ledger's dimensions — the change
  itself (`P1.2 · model · sonnet -> opus`), the resolved author under
  `usage.authorMode`, the session id, and hashes. Never file contents, never
  prompt text, and — since the row below — never a command, a machine path or a
  host name.
- **What it deliberately does NOT record, because the journal is committed.**
  A user found their own user name and their whole directory layout inside a
  committed row ([CWE-532](https://cwe.mitre.org/data/definitions/532.html)),
  which named a person's computer in a repository that goes to clients. Three
  changes, all at the one boundary every writer passes through: a command is
  stored as an unsalted SHA-256 digest, its UTF-8 byte length and its program
  name — never its text; a `cwd` is stored relative to the repository, or as
  `<outside-repo>` when it is not inside one; and `actor.host` is not stored at
  all, because nothing ever read it. The digest exists so a claimed command can
  be *checked* — hash your candidate and compare — which is exactly why it is
  unsalted, and a salt this project could ship would be published with it. So a
  short command drawn from the obvious vocabulary is recoverable by someone
  willing to enumerate that vocabulary; what is never written down is the part
  that identifies a person: the paths, the host names, the arguments. That is
  data minimisation and friction, not anonymisation.

  Existing history is left alone — rewriting a committed row would break
  `verify` on every clone, since the hash covers those exact bytes.
  `tools/check-committed-pii.py` reads what git tracks and fails the build on a
  committed artifact that carries machine identity, with the rows that predate
  the change declared in its `BASELINE` with a reason.
- Hand edits to the journal are refused by `guard-edits.py`. `journal.enabled:
  false` turns the whole thing off.

So it is a smoke detector, not a vault: it makes a quiet change loud, and an
accident visible. If your threat model includes an adversary with write access to
the repository and a motive to cover their tracks, the honest answer is that this
raises the cost and does not close the door — commit the journal, and let the
review of the commit be what closes it.

## The capability policy: what it can and cannot hold

Since 0.30.0 a project can say which skills, subagents and MCP tools may be used
in it (`policy` in `.claude/audit.config.json`, enforced by
`hooks/guard-capabilities.py`). It ships **inert** — every kind defaults to
`allow` with no deny rules — so it changes nothing until someone writes a rule.

It is worth being exact about the reach, because a guard whose limits are
unstated gets relied on for things it cannot do. **Four flags, all of them
consequences of running as a plugin hook rather than as the platform:**

1. **Subagent hooks are not inherited on every version**
   (anthropics/claude-code#43772). Inside a subagent the policy may simply not be
   consulted, which makes it advisory there rather than enforced. There is no way
   for the plugin to detect this per call, so it reports the only local evidence
   it has: `guard-capabilities` leaves a marker when it runs with a live policy,
   and `/audit:doctor` **warns** when an active policy has no marker.
2. **It denies the tool, not the knowledge.** Denying a skill stops the Skill
   tool call. It does not unread a document the model has already been given, and
   it does not stop the same work being done by hand. This is a control over
   *invocation*, which is the only thing a tool hook can see.
3. **The user's own switch outranks it.** Claude Code lets anyone disable a
   plugin — by design — and a disabled plugin's hooks do not run. So the plugin's
   own components (its commands, skills and agents) are **not** deniable through
   its own policy: a rule aimed at them does not take effect, and is reported as
   a validation finding rather than silently ignored. The honest claim is not
   "unremovable" — it is "not removable *quietly*", since removing them means
   disabling the plugin, which is visible in `/plugin` and to `/audit:doctor`.
4. **Hooks cannot gate hooks.** Another plugin's hooks run in the same session
   and nothing here can refuse them. The panel inventories what is installed;
   it never claims to enforce against it.

Everything uncertain resolves to *allow*, in keeping with the fail-open posture
above: no policy engine, a malformed block, an unreadable manifest and an
internal error all permit the call. `onViolation` chooses what a real violation
does — `deny` (refuse), `ask` (manual approval per call) or `warn` (allow it and
say so). `warn` is deliberately **not** a `permissionDecision: "allow"`, which
would bypass the permission system entirely: an advisory must not grant anything.

Blocking uses the canonical PreToolUse JSON protocol
(`permissionDecision: "deny"` + reason, exit 0). Internal errors fail **open**
deliberately: a buggy guard must never brick legitimate work — but that means a
crafted input that *crashes* a guard bypasses it. Every hook has an explicit
10-second timeout.

A **malformed** `.claude/audit.config.json` falls back to defaults — meaning
your custom secret patterns and rules are NOT applied — and is surfaced once
per session (`detect-plan-skip`) and blocks `/audit` at preflight.

## Known bypass classes (accepted, documented)

1. **Arbitrary Bash writes.** `sed -i`, `tee`, `>`/`>>` redirects (incl. heredoc
   redirects) into source files are blocked since 0.3.0, and inline-eval writes
   (`python -c "open(...,'w')"`) are heuristically blocked — full Bash-write
   coverage is statically undecidable (obfuscated redirects; upstream:
   anthropics/claude-code#29709).

   **What that heuristic reads, stated because the residual is the point of this
   list.** A heredoc fed to an interpreter is graded exactly like `-c`/`-e`
   (`python3 - <<PY` is the same capability, spelled differently), and the path a
   write call names is RESOLVED rather than required to be a quoted literal beside
   the call: a literal, a concatenation of literals, or one hop of binding
   (`p = 'src/app.ts'` … `open(p, 'w')`). That last shape is what every two-line
   bulk edit uses, and it walked through until somebody measured it — the pattern
   knew the adjacency rather than the capability, which is the same root as the
   heredoc gap one fix earlier. **Still out of reach, by design rather than by
   oversight**: a path produced by a CALL (`open(find_it(), 'w')`,
   `os.path.join(a, b)`), an f-string, or a chain through a second name. Those need
   dataflow this hook does not do, so it reports no target rather than inventing
   one — and the PostToolUse check below is what covers them. **Since 0.6.0**
   the residual is watched by `guard-bash-writes`, a PostToolUse check that
   diffs `git status` against its own baseline and tells the model in-band. It
   is advisory by nature (PostToolUse cannot undo the write) and needs a git
   repo — no git, a git error or a timeout leaves it silent, and it always exits
   0. **Since 0.27.0** it also reports a shell write into a manifest or phase
   shard held by another live session — previously invisible twice over, since
   `manifestPath` was skipped outright and `.json` is not a source extension.

   **This paragraph used to say it detects ANY shell write into an unplanned
   source file. It does not, and has not since F-P-24.** The real predicate is
   narrower than that, and every exemption below is there because the broad
   version was reporting something that was not true. The count that used to
   stand here rotted the first time an exemption was added; the list is the
   thing to read:

   - **ONE working tree — the configured `gitRoot` — and it says so when a
     command ran in another.** `git status` runs there, and every path in the
     session's state file is a path in that tree. It used to pick that tree with
     `CLAUDE_PROJECT_DIR`, which is the right answer to "where does the config
     live" and the wrong one to "which tree did this command touch": the variable
     stays pinned to the primary checkout while an agent works inside a git
     worktree, so a read-only sweep in the worktree was told it had modified
     source files a parallel session was editing in the primary tree — clean
     where the command ran, dirty where the guard looked. The tree is now git's
     own answer for the command's working directory (`rev-parse
     --show-toplevel`), and `--git-common-dir` separates a linked worktree of
     this repository from a stranger's checkout. A command from a tree this
     guard does not watch gets a notice naming both trees, once per tree,
     instead of an attribution — so shell writes made from there are not checked
     against the plan at all. Opening a session **in** the worktree (what
     `/audit:worktree` prints) restores full coverage, because the hooks then
     resolve their project directory to it.
   - **A NEW dirty path**, relative to a baseline the session's first Bash pass
     seeds silently — not every unplanned write, only one that appears between
     two of this hook's own looks at the tree.
   - **It can prove a command harmless; it cannot prove one guilty.** F-P-24
     bound the evidence to the operation instead of to the tree: a command
     provably unable to write is absorbed and no path is attributed to it. That
     only ever *removes* an attribution — an unrecognised command is still
     watched exactly as before. **The proof is taken over shell TOKENS, not over
     the command text** — before F51 it read the raw string, so a metacharacter
     inside a quoted search pattern was taken for shell syntax and `grep -n
     "cost > 5"` was a redirect. Redirects that name no file are dropped
     (`2>/dev/null`, `2>&1`); any other `>` in the same command survives. A
     command the shell would parse differently than any splitter here can —
     unbalanced quotes, a heredoc — is watched, because a stray notice costs a
     line of text and a miss costs a write nobody was told about. A `find …
     -exec` clause and an `xargs` command are each graded on what they run:
     `-exec cat {} +` and `xargs wc -l` are absorbed, `-exec sed -i …` and
     `xargs rm` are not, and a clause naming no command proves nothing.
   - **With another session writing in the same window it drops the authorship
     claim, not the finding.** A path another session claims is attributed there
     and never mentioned here; for the rest, the report states what is actually
     established — the file was clean at this session's previous look, is dirty
     now, and no `in_progress` task covers it — rather than naming an author.
     The signal is the mtime of sibling session state files; a session merely
     *seeing* a path dirty is deliberately not a claim on it, or two sessions
     could exonerate each other for a file neither wrote.
   - **The path must be a source file** — not exempt, not the manifest or its
     lock, not written by an edit tool, and not covered by an `in_progress` task.
   - **The plan-coverage class is graded on the same evidence as the plan gate**,
     through `_config.plan_gate_mode`: in a repo with no manifest there is no
     plan, so "no task covers this" is vacuously true of every file and the class
     says nothing. `enforce: true` (or `planGate`) restores it as a decision
     someone made. The journal and lock classes are NOT graded — each binds its
     claim to evidence of its own and means the same thing in a repo with no
     plan. Before this, installing the plugin armed the class in every repo on
     the machine, including ones that never opted in.

   So the honest ceiling here is not coverage but **attribution**, and attribution
   is **per tree**. It sees one tree's diff plus the text of one command, and where
   those two cannot name an author — or cannot even name the tree the command ran
   in — it now says so out loud instead of guessing.
2. **Subagents do not inherit parent hooks** in all versions
   (anthropics/claude-code#43772). Mitigations: the `/audit` orchestrator —
   not its subagents — performs all manifest writes and commits; since 0.6.0
   the plugin ships its own agents with PINNED tool lists (`audit-explorer`
   has no Edit/Write/Bash at all, `audit-executor` no web tools,
   `audit-reviewer` no edit tools, and since 0.31.0 `guide` only
   Read/Grep/Glob) — a hard boundary that does not depend on
   hook inheritance; subagent prompts still restate the hard rules.
3. **Self-modification.** `guard-edits` denies edits to the installed plugin's
   own directory and to `plan-bypass-*` state files (bypass forgery), with a
   dev-mode exception when the plugin checkout IS the working repo. Claude Code
   settings/hook wiring files outside the plugin remain editable by design
   (upstream: anthropics/claude-code#32376).
4. **Test-file exemption.** Test files are exempt from plan-first so red-first
   TDD stays frictionless — the first act of a red-first fix is writing a test
   that fails, and a gate that blocks that blocks the discipline. Logic can
   therefore be smuggled into a test file. Compensations: `remind-tdd`
   visibility and the phase review gate, which reads the whole diff.
   **Widened in 0.26.0** from `**/*.spec.*` / `**/*.test.*` — the JavaScript
   spelling only — to also cover `**/*_test.*`, `**/*_spec.*` and
   `**/test_*.*`. `test_cart.py` (what unittest and pytest discover by default)
   and `cart_test.go` (required by the Go toolchain) were being denied, so on
   those stacks the exemption did the opposite of its purpose. The same
   `_config.py` already listed those patterns under `tddReminder.testGlobs`:
   two lists in one file disagreeing about what a test file is. Note this is a
   **wider** bypass than before by design; a project that wants the narrow set
   can pin `exemptGlobs` in `.claude/audit.config.json`.
5. **Bypass residuals.** The single-use `#no-plan` bypass is consumed on
   PostToolUse; several edits batched in ONE assistant message can ride one
   bypass ("single-use per tool batch"). Arming is substring-based: a prompt
   *discussing* the keyword arms it (you are told when that happens). Since
   0.6.0 a forgotten armed bypass expires with the 7-day state GC.
6. **Secret-read guard is name-based.** It blocks by path/token patterns
   (`.env`, `credentials*`, key/cert extensions + your `secretPatterns.extra`).
   A secret in an unconventionally-named file is invisible to it. It
   deliberately over-blocks on the read side (e.g. any `.pem`, including public
   certs; `cp .env.example .env`) — a harmless retry beats an irreversible leak.
7. **State files are plaintext.** `.claude/state/` and `.claude/logs/` in the
   consuming repo hold session state and the bypass log (no secrets). Add them
   to your `.gitignore`. Files older than 7 days are garbage-collected
   opportunistically on prompt submission (since 0.6.0).

## Reporting a vulnerability

Email **alek.bisevac@gmail.com** (subject: `[quality-gates security]`). Please
do not open public issues for exploitable weaknesses in the guards. You can
expect an acknowledgment within a week. Hardening ideas that are already listed
above as accepted trade-offs are welcome as regular issues/PRs.
