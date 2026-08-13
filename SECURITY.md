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

## Fail modes (by design)

All **nine** hook scripts launch through `hooks/py-launch.sh`, which resolves
`python3` → `python` → `py`. The fail mode when **no interpreter exists** is
hardcoded per hook in `hooks/hooks.json` — it cannot live in
`.claude/audit.config.json` because reading that config requires Python
(chicken-and-egg).

The table has **ten rows for nine scripts**: `require-plan` is registered
twice, once on `PreToolUse` to decide and once on `PostToolUse` to commit that
decision, and the two registrations fail differently — which is the whole reason
this table is per-registration rather than per-script. Elsewhere you may see
"seven guard hooks": that is the seven that guard, excluding `meter-usage` and
`journal-writes`, which only record. Three defensible counts, so each one now says
what it counts.

| Hook | Event | No interpreter | On internal error |
|---|---|---|---|
| `guard-secrets-read` | PreToolUse Read/Grep/Bash | **ask** (manual approval prompt, loud) | allow (fail-open) |
| `guard-edits` | PreToolUse edits | **ask** | allow |
| `require-plan` | PreToolUse edits | **ask** | allow |
| `guard-capabilities` | PreToolUse Skill/Task/Agent/MCP | **ask** | allow |
| `require-plan` (state commit) | PostToolUse edits | silent | no-op |
| `guard-bash-writes` | PostToolUse Bash + edits | silent | no-op |
| `remind-tdd` | PostToolUse edits | silent | no-op |
| `journal-writes` | PostToolUse edits | silent | no-op |
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
(`scripts/audit-journal.py`, written by the `journal-writes` hook and by the
panel's own saves). Each row carries who, when, what changed, a hash of the
document the write left behind, and the hash of the row before it.

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
- **What it never sees.** Shell writes (`sed -i`, `>`) do not reach a tool matcher,
  so nothing records them — they surface instead as out-of-band drift, and
  `guard-bash-writes` reports a shell write *into the journal directory* after the
  fact. Anything written while the plugin is disabled is invisible for the same
  reason every other guard is: the user's own switch outranks it.
- **What it records.** The same shape as the ledger's dimensions — the change
  itself (`P1.2 · model · sonnet -> opus`), the resolved author under
  `usage.authorMode`, the session id, the host, and hashes. Never file contents,
  never prompt text.
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
   coverage is statically undecidable (heredocs piped into interpreters,
   obfuscated redirects; upstream: anthropics/claude-code#29709). **Since
   0.6.0** the residual is covered by `guard-bash-writes` — a PostToolUse
   `git status` diff check that detects ANY shell write into an unplanned
   source file after the fact and tells the model in-band. It is advisory by
   nature (PostToolUse cannot undo the write) and needs a git repo. **Since
   0.27.0** it also reports a shell write into a manifest or phase shard held
   by another live session — previously invisible twice over, since
   `manifestPath` was skipped outright and `.json` is not a source extension.
2. **Subagents do not inherit parent hooks** in all versions
   (anthropics/claude-code#43772). Mitigations: the `/audit` orchestrator —
   not its subagents — performs all manifest writes and commits; since 0.6.0
   the plugin ships its own agents with PINNED tool lists (`audit-explorer`
   has no Edit/Write/Bash at all, `audit-executor` no web tools,
   `audit-reviewer` no edit tools, and since 0.31.0 `audit-guide` only
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
