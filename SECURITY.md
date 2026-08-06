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

All six hooks launch through `hooks/py-launch.sh`, which resolves
`python3` → `python` → `py`. The fail mode when **no interpreter exists** is
hardcoded per hook in `hooks/hooks.json` — it cannot live in
`.claude/audit.config.json` because reading that config requires Python
(chicken-and-egg):

| Hook | Event | No interpreter | On internal error |
|---|---|---|---|
| `guard-secrets-read` | PreToolUse Read/Grep/Bash | **ask** (manual approval prompt, loud) | allow (fail-open) |
| `guard-edits` | PreToolUse edits | **ask** | allow |
| `require-plan` | PreToolUse edits | **ask** | allow |
| `require-plan` (state commit) | PostToolUse edits | silent | no-op |
| `guard-bash-writes` | PostToolUse Bash + edits | silent | no-op |
| `remind-tdd` | PostToolUse edits | silent | no-op |
| `detect-plan-skip` | UserPromptSubmit | silent | no-op |
| `meter-usage` | Stop / SubagentStop / SessionEnd | silent | no-op |

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
   nature (PostToolUse cannot undo the write) and needs a git repo.
2. **Subagents do not inherit parent hooks** in all versions
   (anthropics/claude-code#43772). Mitigations: the `/audit` orchestrator —
   not its subagents — performs all manifest writes and commits; since 0.6.0
   the plugin ships its own agents with PINNED tool lists (`audit-explorer`
   has no Edit/Write/Bash at all, `audit-executor` no web tools,
   `audit-reviewer` no edit tools) — a hard boundary that does not depend on
   hook inheritance; subagent prompts still restate the hard rules.
3. **Self-modification.** `guard-edits` denies edits to the installed plugin's
   own directory and to `plan-bypass-*` state files (bypass forgery), with a
   dev-mode exception when the plugin checkout IS the working repo. Claude Code
   settings/hook wiring files outside the plugin remain editable by design
   (upstream: anthropics/claude-code#32376).
4. **Test-file exemption.** `**/*.spec.*` / `**/*.test.*` are exempt from
   plan-first so TDD stays frictionless — logic can be smuggled into a test
   file. Compensations: `remind-tdd` visibility and the phase review gate.
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
