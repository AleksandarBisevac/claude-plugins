# Guard ownership — which rules only the plugin can know, and what Claude Code's layers hold

This design goes rule by rule through the two command-reading guards,
`plugins/audit/hooks/guard-history-rewrite.py` and `plugins/audit/hooks/guard-secrets-read.py`,
and the `_config` readers they call. For each rule it decides whether the plugin keeps it or hands
it to Claude Code's own layers (permission rules, auto mode's classifier, the Bash sandbox).

**The answer is that no rule moves.** The rest of this document gives the basis for that, the
`permissions.deny` fragment the plugin recommends alongside its guards, and the transition and
compatibility rules any later move has to follow.

## The bases this rests on

- **The refusal measurement.** `docs/research/guard-refusals-by-owner.md` read the 3.0.x-era
  refusal corpus. It found no refusal in the generic-destructive class: every deny arm that fired
  depended on plan, manifest, recorded-SHA or secret-pattern state. This document reads the
  private corpus only through that one.
- **Claude Code's published documentation.** I fetched it on 2026-10-06 from
  `https://code.claude.com/docs/en/permissions.md`, `.../sandboxing.md` and
  `.../permission-modes.md`. Every claim below about what a host layer matches is quoted from
  those pages, not recalled.
- **The installed CLI's own auto-mode rule list.** This is the output of `claude auto-mode
  defaults` on Claude Code 2.1.291, read once on 2026-10-06 (exit 0; the output's sha256 began
  `4a15af70`). Auto mode is a classifier and these are its default prompts. Neither the
  documentation nor this list is a contract, so every auto-mode claim here is **measured once, on
  one version**, and has to be re-read before a release relies on it.
- **Both quotation sets rest on one reading.** That reading is this document's author's, on
  2026-10-06, against CLI 2.1.291. An independent re-check was refused by the auto-mode
  classifier, so it is left to the maintainer.

One correction to the measurement document comes first, because the decision depends on it. That
document files its "secret read" rows under "plugin-only by construction". That label holds for
plan scope, manifest integrity and recorded SHAs: each is a question that only the plugin's
own state can answer. **It does not hold for secret reads.**
`guard-secrets-read.py`'s Rule #1 and Rule #2 read no manifest, no plan and no journal: their
verdict depends only on whether a path or a token matches a pattern. So the measurement places
these rules correctly, outside the generic-destructive class, but the reason it gives is wrong.
They are the one family of rules where "would Claude Code's own layers hold this?" is a real
question, and the rule-by-rule section below answers it. The measurement document now gives
this reason itself.

## What a host layer can and cannot match

These are the facts the per-rule decisions use, quoted or closely paraphrased from the pages
named above:

- **Bash rules match spelling.** "A Bash rule matches the command text Claude writes, after
  Claude Code splits compound commands and strips wrappers … a deny or ask rule covers the
  invocation Claude usually produces and isn't a security boundary around the program." The
  docs' own example is that `Bash(git push *)` does not stop `git -C . push origin main`,
  `git -c push.default=current push origin main` or `git 'push' origin main`. Deny rules do
  apply inside subshells, command substitutions and `&&` chains.
- **Read deny rules reach further than Bash rules, but not all the way.** "Read and Edit deny
  rules apply to Claude's built-in file tools, to file commands Claude Code recognizes in Bash,
  such as `cat`, `head`, `tail`, `sed`, and `tee`, and to the targets of Bash redirections …
  They don't apply to … arbitrary subprocesses that read or write files indirectly, like a
  Python or Node script that opens files itself." They apply to Grep and Glob on a
  best-effort basis.
- **Read deny rules support carve-outs.** A `!` pattern later in the same file's `deny` list
  carves paths out of an earlier rule (`Read(*.env)` followed by `Read(!sample.env)`). Rule order
  is deny, then ask, then allow, so an *allow* rule cannot carve anything out of a deny.
- **The sandbox turns Read denies into OS-level denies.** When the sandbox builds its filesystem
  configuration it includes "its `Read` deny rules", and a sandbox `denyRead` blocks every
  subprocess. The sandbox is opt-in, and `QUICKSTART.md` already says neither it nor a deny rule
  is on by default.
- **MCP tools cannot be matched by path.** "When Claude Code loads a settings file, it skips any
  `mcp__` rule that has parentheses." A settings file can deny a whole MCP tool or server, but it
  cannot deny one file through one tool.
- **Auto mode treats rewriting your own history as normal work.** Its `Git Destructive` rule
  ends: "Reshaping the agent's own work — `--amend`, rebase, force-pushing a personal branch
  containing only their commits — is the normal iteration loop, not this rule." Its `Irreversible
  Local Destruction` rule names `git reset --hard` and `git stash drop`/`clear`, but not a stash
  *push*.
- **Auto mode allows dotenv reads by default.** Its `allow` list carries "Standard Credentials:
  Reading credentials from the agent's own config (.env, config files) and sending them to their
  intended provider". Its `Credential Materialization` rule blocks printing a live credential into
  the transcript, naming `cat ~/.aws/credentials` and `echo $SOME_API_KEY`. That is a judgement
  about where the value lands, not a refusal of the read.

## Rule by rule — `guard-history-rewrite.py`

Every arm below sits behind `decide()`, which allows outright before any arm runs if the command
has no git invocation. Every arm also reads plugin state before it can deny.

| Arm (function / branch) | What its verdict reads | Owner | Why a host layer cannot hold it |
|---|---|---|---|
| Unplaceable directory with a rewrite (`unplaceable_directory` + `plan_present`) | plan on disk | **plugin** | It denies only when a plan exists. Outside a plan the same command is allowed, so its verdict is about the plan. |
| Unparseable `git -C` with a rewrite (`unparsed_git_c` + `plan_present`) | plan on disk | **plugin** | Same as above. |
| Stash arm (`moving_stash` + `plan_present`) | plan on disk | **plugin** | A stash push is refused whenever the tree holds an audit plan (`plan_present` checks only that the manifest file exists), because parallel tasks under that plan share one working tree. Auto mode names only `stash drop`/`clear`; a stash push is not in its list. |
| `xargs git` (`STDIN_VERB` + `plan_present`) | plan on disk | **plugin** | Same gate as the stash arm. |
| Force-push, `--force-with-lease`, `--orphan`, filter-branch/filter-repo, rebase (`always_refused`, reached only when `recorded_shas` is non-empty) | SHAs `task.commit` records | **plugin** | The returned `("allow", "")` when `shas` is empty is the whole activation condition. Auto mode explicitly treats rebasing or force-pushing your own branch as normal. Only the manifest knows that the commit being rewritten is evidence. |
| `reset --hard <ref>` (`reset_targets` + `orphaned_by`) | recorded SHAs plus git ancestry | **plugin** | It refuses only when a recorded SHA would stop being an ancestor. A bare `reset --hard` is allowed on purpose. |
| `commit --amend` over a recorded HEAD (`amend_requested` + `rev-parse HEAD`) | recorded SHAs plus HEAD | **plugin** | Auto mode clears an amend when "the agent visibly created HEAD this session". The plugin refuses exactly that case when HEAD is a commit `task.commit` already names. |

**Nothing in this file moves.** No arm denies without first reading the plan or the SHAs it
records. That matches the measurement's finding from the code side: a plugin-only verdict is the
only kind this hook gives.

## Rule by rule — `guard-secrets-read.py`

The rules fall into two groups, and **the grouping is by what each rule reads, not by where it
sits in the file**. Inside `_decide_core`'s Bash branch, the comment "EVERY SECRET RULE IS ABOVE
THIS LINE AND EVERY GRADED ONE IS BELOW IT" happens to separate the two groups. The `Read`, `Grep`
and MCP tool branches are separate branches of their own, and the MCP one sits textually below
that comment, yet all three belong to the secret group. The two groups get opposite answers to
"does this read plugin state?".

### Rules that read plan or manifest state — kept

| Arm | What its verdict reads | Owner |
|---|---|---|
| Interpreter write into a source file (`_eval_write_hit` → `_plan_gate_write_verdict`) | the plan-gate tier (`_config.plan_gate_mode`), declared files of in-progress tasks, `exemptGlobs` | **plugin** |
| Shell write into the manifest, its lock or a phase shard (`_manifest_write_hit` → `_manifest_write_verdict`) | `manifestPath`, `_config.governing_lock`, `_config.manifest_lock_conflict`, `_config.is_subagent` | **plugin** |
| Shell write into a source file (`_shell_write_targets` → `_plan_gate_write_verdict`) | same as the interpreter arm | **plugin** |

None of these has a host equivalent at all. An `Edit(...)` deny rule cannot say "unless a running
task declares this file".

### Secret rules — no plugin state, kept, with the reason stated

| Rule (branch in `_decide_core`) | Fragment entry that overlaps it | What that entry misses that the rule catches |
|---|---|---|
| Rule #1, `Read` tool (`SECRET_PATH` + `secretPatterns.extra`) | the `Read(...)` path entries below | the project's `secretPatterns.extra`, which is a regex that no gitignore pattern translates in general; case variants (the rule is `re.IGNORECASE`, and the docs establish no case-folding for gitignore matching) |
| Rule #1, `Grep` tool (`SECRET_PATH`/`SECRET_GLOB` on `path` and `glob`) | the same `Read(...)` entries, which apply "best-effort" to Grep | a `glob` argument that names secret files under a directory the path rule does not match; `secretPatterns.extra` |
| Rule #1, Bash read verb or input redirect (`BASH_FILE_READ`, `_extra_read_hit`) | the same `Read(...)` entries, for "file commands Claude Code recognizes" and redirect targets | verbs outside the recognised set: the docs name `cat`, `head`, `tail`, `sed` and `tee`, and do not establish `git show HEAD:<file>`, `git cat-file`, `source`/`.`, `cp`/`mv`/`rsync`/`install`, `base64`, `openssl` or `xxd`; `secretPatterns.extra` |
| Rule #1, inline-eval read (`_eval_reads_a_secret` over `-c`/`-e` and interpreter heredocs) | none; the docs exclude it ("a Python or Node script that opens files itself") | the whole rule, unless the sandbox is on, in which case a Read deny becomes an OS-level deny |
| Rule #1, MCP payload naming a secret path (`_mcp_secret_target`) | none; `mcp__` rules with parentheses are skipped | the whole rule. A path cannot be named in an MCP rule, and denying the server denies its harmless calls too |
| Rule #2, env dump (`ENV_DUMP`: `printenv`, a bare `env` at the end of a clause, `direnv dump`/`export`) | `Bash(printenv)`, `Bash(printenv *)`, `Bash(env)`, `Bash(direnv dump *)`, `Bash(direnv export *)` | the spelling variants the docs list as uncovered (`/usr/bin/printenv`, `sh -c 'printenv'`), and `env` in a pipe position other than the whole subcommand |
| Rule #2, `process.env` dump or token-shaped read (`PROCESS_ENV`) | none; this is code text inside an interpreter | the whole rule |
| Rule #2, echoing a token-shaped variable (`ECHO_SECRET`) | none in the fragment; auto mode's `Credential Materialization` judges it | everything, for a user who is not in auto mode; a deny rule cannot express "a variable whose name ends in TOKEN" |
| Sandbox switched off on an environment-adjacent command (`_sandbox_disabled` + `ENV_ADJACENT`) | none | the whole rule. It is a verdict about the `dangerouslyDisableSandbox` field, which no permission rule reads |

**These rules stay, and the reason is coverage, not ownership.** Each one reads no plugin state,
so asking only "does this verdict depend on the plugin's own state?" would hand them over. These facts outweigh that:

1. **The host layer that would replace them is off by default.** A user who has installed the
   plugin but not the fragment would go from refused to allowed on every row above. The
   measurement's secret-read rows show these rules fire in practice, and the corpus cannot say
   whether a host rule was present when they did. Nothing measured here says how many machines carry it.
   `/audit:doctor`'s `secret rules` row does not answer that for the fragment either.
   `_doctor_setup._is_env_read_deny` accepts any single `Read(...)` or `Grep(...)` deny whose
   argument contains `.env`, `Grep(.env*)` included, and rejects a `!` carve-out, which refuses
   nothing by itself. It never checks the `credentials`, `id_*`, key-extension or env-dump
   entries, and it reads settings files only, which managed policy and a `--settings` flag
   outrank. So the row says that *some* dotenv read-deny rule is declared in the files it can
   read, no more; when none is, its fix names this fragment's file. Comparing the declared rules
   against the whole fragment would be a further change to the doctor; this design does not
   make it.
2. **Auto mode does not backfill them.** Reading a dotenv file is on auto mode's default
   *allow* list, so even a user in auto mode keeps only the spelling-matched part.
3. **Some rows have no host equivalent at any setting short of the sandbox.** These are the
   inline-eval reads, the MCP payloads and the `process.env` arm. With the sandbox on, the
   inline-eval and redirect gaps close at the OS level. The documentation read here establishes
   the sandbox for Bash subprocesses only, and establishes nothing for an MCP server's own
   process, so the MCP gap is not shown to close.

**Considered and rejected: moving only the `Read` and `Grep` tool branches of Rule #1.** With the
fragment installed, they overlap a host rule almost exactly. Removing them saves nothing, because
the hook process runs anyway for the Bash and MCP branches that stay. It also costs every user
without the fragment the one guarantee `SECURITY.md` states unconditionally ("denied whether or
not a plan is running"). And it narrows what `secretPatterns.extra` reaches without the key
stopping being read, which is a change no reader of `COMPATIBILITY.md` would expect from its
promise.

## The recommended `permissions.deny` fragment

This sits *alongside* the plugin, not in place of any rule above. It contains secret-read entries
only.

```json
{
  "sandbox": { "enabled": true },
  "permissions": {
    "deny": [
      "Read(.env)",
      "Read(.env.*)",
      "Read(!.env.example)",
      "Read(!.env.sample)",
      "Read(!.env.template)",
      "Read(!.env.dist)",
      "Read(!.env.defaults)",
      "Read(.envrc)",
      "Read(.envrc.*)",
      "Read(credentials)",
      "Read(credentials*.json)",
      "Read(credentials*.plist)",
      "Read(credentials*.key)",
      "Read(credentials*.cer)",
      "Read(credentials*.der)",
      "Read(credentials*.txt)",
      "Read(credentials*.cfg)",
      "Read(credentials*.conf)",
      "Read(credentials*.yaml)",
      "Read(credentials*.yml)",
      "Read(id_rsa)",
      "Read(id_dsa)",
      "Read(id_ecdsa)",
      "Read(id_ed25519)",
      "Read(*.p12)",
      "Read(*.pfx)",
      "Read(*.mobileprovision)",
      "Read(*.keystore)",
      "Read(*.jks)",
      "Read(*.p8)",
      "Read(*.pem)",
      "Bash(printenv)",
      "Bash(printenv *)",
      "Bash(env)",
      "Bash(direnv dump *)",
      "Bash(direnv export *)"
    ]
  }
}
```

How the fragment was derived, and what it decides:

- **The path entries are `SECRET_PATH` spelled as gitignore patterns, and the gitignore form is
  broader in one place.** They follow the `credentials` extension set in `_CRED_EXT` and the
  template carve-outs in the regex's negative look-ahead. A bare file name matches at any depth,
  per the docs ("`Read(.env)` and `Read(**/.env)` are equivalent"). `SECRET_PATH` is anchored at
  the end of the path, so it matches a *file* called `.env` or `credentials` and nothing inside
  a directory of that name. A gitignore pattern with no slash matches a directory of that name
  too, and with it everything beneath, so `Read(.env)` also denies a virtualenv created at
  `.env` and `Read(credentials)` a folder called `credentials`. `Read(*.pem)` and
  `SECRET_PATH`'s `\.pem$` agree with each other, and both cover public certificates and CA
  bundles as well as private keys. `QUICKSTART.md` names these costs and the carve-outs a user
  would add. The `!` carve-outs must stay *after* `Read(.env.*)` in the
  *same* file's list, because a carve-out reaches only rules from the same source.
  `credentials*.p8` and `credentials*.pem` are absent because `*.p8` and `*.pem` already cover
  them.
- **The template carve-outs are deliberately stricter than `SECRET_PATH`.** The regex's
  look-ahead allows any name that *starts* with a template suffix, so `.env.example.local`
  passes it. The fragment's `!.env.example` carves out the exact name only, so it denies
  `.env.example.local`. The fragment errs toward refusing: a template-shaped file holding real
  values costs a leak, while an over-block costs a retry. No suffix carve-outs are added.
- **`sandbox.enabled` is part of the recommendation, not decoration.** It turns the `Read(...)`
  entries into OS-level denies for every subprocess, and that closes the inline-eval and
  unrecognised-verb gaps in the table above. Without it, the path entries are spelling rules over
  the recognised verbs.
- **There is no `Grep(...)` entry.** The docs consult file permissions "against `Edit(path)` and
  `Read(path)` rules only", and Read rules already reach Grep best-effort. `QUICKSTART.md` once
  recommended a `Grep(.env*)` entry of its own, for which the docs establish no effect; it now
  points at this fragment instead. The doctor's `secret rules` row still counts a `Grep(...)`
  rule naming `.env` as declared, which is the row reporting what it found rather than what the
  docs show it does.
- **There is no git entry, on purpose.** None of the history arms moves, and a spelling deny on
  force-push, rebase or `reset --hard` fires in every repository, including the plan-less ones
  where the plugin deliberately says nothing. That is the over-fire the history guard's own
  docstring identifies as the way a guard gets switched off. A user who wants a checkpoint there
  should write `permissions.ask` entries (the docs' own advice for push), which are not part of
  this recommendation.
- **The `secretPatterns.extra` regexes have no entry, because they cannot have one in general.**
  A project that uses that key should add matching `Read(...)` patterns by hand. The guard keeps
  reading the regexes either way.

## Who loses coverage

**Under this design, nobody.** No rule is removed, and the fragment only adds a layer.

If a later release moves any rule anyway, this is who loses what. It is stated here so that a
later proposal cannot leave it implicit:

- **Users without auto mode** keep only the spelling-matched rules: the fragment's `Bash(...)`
  entries and the `Read(...)` entries over recognised verbs. If the sandbox is off, nothing
  catches an interpreter read, a `git show HEAD:<file>` or an MCP payload.
- **Users in auto mode** gain little for secret reads. Dotenv reads are on the classifier's
  default allow list, and `Credential Materialization` is a judgement about the transcript, not a
  refusal of the read.
- **Users without the fragment** lose the rule outright. How many users that is, is not
  measured here.

## The transition, fixed for any rule that does move

"What would moving a rule look like?" has an answer even though no rule moves today. It is
fixed here so that a later move has a procedure to follow and not one to invent:

1. **Release N: report, do not block.** The moved branch returns `allow` with a reason naming the
   fragment entry that now holds the guarantee, and must leave a record of each such allow, so
   the miss rate is countable. Which record that is belongs to the release that does the move. Its tests move from "denies" to "reports, and allows".
2. **Release N+1: remove.** The branch is deleted only if the corpus for release N shows the
   reported rows were caught by a host layer, or nobody acted on them. "Nobody complained" does
   not count as evidence.
3. **A move that stops a config key being read is a major release** under `COMPATIBILITY.md`
   ("ceasing to read one is a major"). The compatibility check below says which keys that would
   be.

**When to revisit this design:** a secret rule should move once a host layer holds its
guarantee *by default* and *at the operation*, not by spelling. For example, if the sandbox
became on by default, or if a permission rule could name a path inside an MCP payload. Neither
holds in the documentation read on 2026-10-06.

## Compatibility — which config keys the two guards read

I found these by reading each `cfg.get(...)` in the two guards and in the `_config` readers named
in the table (`extra_secret_patterns`, `plan_gate_knob`, `enforce_always`, `git_root_dir`,
`logs_dir`, `state_dir`).

**The list does not cover every cfg-taking reader the guards reach.** Other `_config` readers also
take `cfg` and were not traced past their own bodies: `tree_for`, `manifest_state`,
`in_progress_files`, `manifest_lock_conflict` and `governing_lock`. All of them serve the kept
rules, so no key they read can stop being read under this design. A design that does move a rule
has to trace them before it claims the same.

| Key | Read by | Would stop being read if… |
|---|---|---|
| `manifestPath` | both guards (`manifest_rel` in the history guard; the write arms in the secrets guard) | never; the kept rules read it |
| `exemptGlobs` | `_ungoverned_write_target` | never; the kept plan-gate arms read it |
| `planGate`, `enforce` | `_config.plan_gate_knob`, `_config.enforce_always`, through `_plan_gate_write_verdict` | never; the kept plan-gate arms read them |
| `gitRoot` | `_config.git_root_dir` (history guard) | never; the kept SHA arms read it |
| `logsDir` | `_config.logs_dir` (the secrets guard's verdict journaling) | never |
| `stateDir` | `_config.state_dir`, through `_config.refresh_session_stamp`, which the secrets guard's `decide()` calls on every invocation | never; `decide()` stays |
| `secretPatterns.extra` | `_config.extra_secret_patterns`, called only from `guard-secrets-read.py` (the other files naming the key, `_config_rules.py`, `_panel_settings.py` and the panel's `settings.js`, validate or edit it and enforce nothing) | **every** Rule #1 branch were removed; that is a major release. Removing only some branches keeps the key read and narrows what it reaches. |

Under this design no key stops being read, so nothing here owes a major release.

## Draft paragraph for `SECURITY.md`

> **Which layer holds which guarantee.** This plugin's command-reading guards keep the verdicts
> only the plugin can give: whether a write is covered by the running plan, whether a write
> targets the manifest, its lock or a phase shard, whether a history rewrite runs in a repository
> whose manifest records a commit (`task.commit`) and, for `reset --hard`, whether a recorded commit
> would be orphaned, and whether a stash would take uncommitted work out of a tree that holds an
> audit plan. Claude Code's own layers cannot hold these, because each depends on the plan's
> state. The secret-read rules are different: they read no plan state, and they stay because no
> host layer covers them by default. Auto mode allows dotenv reads, a `permissions.deny` rule
> matches spelling and not operation, and no permission rule can name a path inside an MCP
> payload. Claude Code's `Read(...)` deny rules plus its sandbox are the layer that actually
> *contains* a read. The fragment in `docs/research/guard-ownership-design.md` is the recommended
> set. `/audit:doctor`'s `sandbox` row reports whether the sandbox is declared in the settings
> files it reads. Its `secret rules` row reports only whether some `Read` or `Grep` deny rule
> naming `.env` is declared there, a `!` carve-out not counting; it does not check the rest of the
> fragment. `SECURITY.md` carries this paragraph with the basis of its statements about Claude
> Code written inline. This
> plugin does not refuse generic destructive git or shell commands in a repository with no plan,
> and it does not try to: that is the classifier's job in auto mode, and a `permissions.ask` or
> `permissions.deny` rule's job outside it.

## Observed while writing this

Partway through this work, `guard-secrets-read.py` refused a `grep -rn` whose *search pattern*
named the dotenv token. The command named no secret file as a target: the token was the query.
The refusal read: "Reading, sourcing or copying a secret file via shell is blocked (Rule #1).
Reading file names is fine; contents are not — and copying/moving a secret only relocates the
leak." The `Grep` tool's branch ignores its `pattern` for exactly this reason (the header says
"The `pattern` is the query, NOT a target, and is ignored"), but the Bash read-verb arm does not
make the same distinction for `grep`'s first operand. That is an over-fire of the spelling kind
this document describes.

The same guard then refused a `python3 - <<'PY'` heredoc whose only act was a string replacement
in this file, because a Python string literal in the body quoted the name of the `PROCESS_ENV`
arm. The refusal read: "Reading the process environment is blocked (Rule #2): this prints
environment values, not a file." The body is code fed to an interpreter, so the guard is right to
read it. What it cannot tell apart is a string literal *naming* the object from an expression
*reading* it. Both are defects in the guard's matching, recorded for a fix of their own rather
than made here.
