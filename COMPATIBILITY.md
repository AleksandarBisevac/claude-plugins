# Compatibility

What a version number promises here, which two files that promise is about, and
where it stops.

## When this takes effect, and why it is written early

A leading zero promises nothing, and that is the honest reading of every release so
far: `0.x` says the shape may still move. This document states the contract that
takes effect at the first `1.0`, and it deliberately does **not** say that `1.0` has
shipped — `plugins/audit/.claude-plugin/plugin.json` is the only thing that says
which version has, and the release cadence is visible in `git tag` against
`git log --reverse --format=%ad | head -1`.

It is written before that release rather than with it, because a promise drafted the
day it is needed is a promise shaped by what was convenient that day. Nothing below
is aspirational: each rule is either already how releases have behaved, with the
evidence named, or it is marked as taking effect at `1.0`.

**The cost is stated rather than discovered later.** A promise buys adoption with
release velocity: a change that would break either contract below stops being
something the next minor can carry and becomes something that waits for a major.
That is the trade, made on purpose.

## What the version number means from 1.0

| Part | May it break a contract below? | What it carries |
|---|---|---|
| MAJOR | yes — and it is the only one that may | a removed config key, a dropped `meta.version`, a changed precedence |
| MINOR | no | new commands, new config keys, a new `meta.version`, new behaviour |
| PATCH | no | fixes |

Two surfaces are under the promise, and only two: the **manifest** you keep in your
repository, and the **config** you keep in `.claude/audit.config.json`. Both are
files *you* own and the plugin reads. That is the whole basis for the choice — an
upgrade must never invalidate a file you wrote.

## 1. The manifest schema version — `meta.version`

`meta.version` is a required integer in the manifest's `meta` block. It counts
**layouts**, not releases: `2` is the single-file manifest, `3` is the sharded one
where `manifestPath` is an index and each phase body lives in a `phases/`
directory beside it. Both are
current. Neither is legacy, and a mutating command does not nudge you off either.

### Promised

- **A `meta.version` a released plugin accepts is never dropped.** Every later
  release in the same major line reads it. Your manifest keeps loading.
- **A new integer means a new on-disk layout and nothing else.** It is never
  incremented to mark a feature, so branching on it stays meaningful. Adding one is a
  minor release; ceasing to read one is a major.
- **Unknown keys are tolerated, at the root and inside `meta`.** A manifest carrying
  keys a given release does not know about validates. Keys from named earlier
  releases produce neither a finding nor a warning — that is pinned by case, not
  by intent.
- **Validation stays additive.** A manifest that validates against a release keeps
  validating against every later one in the major line. The repository rule behind
  this is in `CONTRIBUTING.md` under *Hard rules*, and it predates this document.

  **F294 is the first thing announced under this promise rather than excused from
  it, and the promise HOLDS through the whole 2.x line.** A task in
  `tests.mode: "tdd"` that is **not** `done` or `cancelled` should write each
  `tests.add` entry as `"<path>: <what it asserts>"`. From **2.3.0** an entry naming
  no file is a **warning**, and its text names both the shape to write and the
  release the refusal arrives in; at **3.0.0** it becomes a **finding**. Nothing
  that validated before 2.3.0 stops validating inside 2.x — that is the promise, and
  the warning is what buys the time to act on it.

  **Why the interim is a warning and not a permanent softness.** The rule exists
  because of what the field is *for* at that mode: `/audit:task add` and `scope` put
  the path an entry names into the task's `files` precisely so `commit_scope` will
  allow the case file the task says it will create — and when the entry is prose
  there is no path to carry, so the permission was never granted and the task's own
  commit trips a scope the operator had just set. That is worth refusing, and it
  will be refused. What a major release buys is the ORDER: announce, then enforce.
  A rule that only ever warns would be the softer answer this is not.

  **What the rule's shape bounds, and what it does not.** The schema stays
  permissive, so nothing about the field's *type* changed; `regression` and
  `gate-only` entries stay free prose, which is the shape most of them have; and a
  `done` or `cancelled` task is exempt, because its `tests.add` is a record of work
  already judged and F283 leaves its scope append-only — a line there would be
  permanent with no remedy. The repair for a live one is to name the file:
  `/audit:task scope <id> --tests-add "<path>: …"`.

  **It reached this plugin's own workflow, and that was found by review rather than
  by the corpus.** Three prescriptions produced entries the rule warns about:
  `commands/bug.md`'s materialized fix task, `commands/init.md`'s finding-to-task
  step, and the `suggestedTests` the explorer agent returns as prose. All three now
  prescribe the `"<path>: <what it asserts>"` shape, so the workflow complies with
  the rule the plugin ships — and the honest reading of the earlier claim that "the
  only entries the rule reaches are already-settled tasks it exempts" is that it
  described the committed manifests **after** the shipped example had been edited to
  satisfy the new rule in the same change, and said nothing at all about the entries
  the commands generate. A rule measured only against a corpus is measured against
  half of its input.
- **A manifest key a released version READS keeps being read** — the promise the
  config section below makes about a config key, made here for the same reason: the
  manifest is a file you wrote. `phases[].adoTracked` is the newest one. A phase
  carrying `adoTracked: false` stays off the Azure DevOps board `/audit:sync` pushes
  to, and its tasks with it; **absent keeps meaning tracked**, which is what makes
  adding the key free — a plan that never writes it behaves exactly as it did before,
  so it is a minor. Ceasing to read it, or reversing what absence means, is a major.
- **`meta.merge` is under the same promise, and absence is the load-bearing half.**
  Three booleans — `auto`, `removeWorktree`, `deleteBranch` — decide what phase
  sign-off does once every task is done. **Absent reads as ON, per key rather than
  per block**, and that is what makes adding them free: a plan that never writes the
  block behaves exactly as it did before, and a plan carrying `{"auto": false}`
  still removes the worktree and deletes the branch, because the three answer
  different questions. Ceasing to read a key, or reversing what its absence means,
  is a major. `meta.developmentBranch` was already read and stays read; what is new
  is that `phases[].parentBranch` overriding it is now settable from the panel, which
  changes no meaning.
- **`testEvidence` is under the same promise, and is deliberately three keys.**
  A task or a phase may carry `{runId, status, at}` pointing at the run that last
  exercised it. **Absent means no run has been recorded** — never "failed" — which is
  again what makes adding it free. It is a **cache**, not the truth: the record lives
  in the evidence file beside the manifest, deleting the block is always safe, and
  `runId` is **opaque** — its format is not a schema and must not be parsed. What is
  promised is that the key keeps being read and that absence keeps meaning what it
  means. `status` **may gain members** — that is the standing "an enum gains no
  members" exclusion below, and code switching on it needs a default arm.
  The **contents of the evidence file itself are not promised**, for the reason the
  usage ledger's NDJSON fields are not: it is a record this plugin writes and
  re-derives, and the manifest block is the interface.

### Not promised

- **That newer releases add no keys.** They will. Your reader must tolerate keys it
  does not recognise, exactly as the plugin tolerates yours.
- **Forward compatibility.** A manifest written by a newer release loads on an older
  one because unknown keys are tolerated — it is not *promised* to, and the older
  release will not act on what it cannot see. The promise runs one way: forward in
  time, never backward.
- **The text of findings and warnings.** They are for a human reading a terminal.
  Parse the exit code — the validator's own `--help` states which code means what —
  never the wording.
- **The WORDING a command uses to report on a key it reads.** `/audit:sync status`
  sorts the manifest's items into classes and `/audit:sync push` prints what a run
  will skip; a later release may relabel a class, add another, or lay the table out
  differently, the same way findings above may be rephrased. What is promised is that
  the key keeps being read and that absence keeps meaning what it means. Anything
  automated reads the manifest, never the table.
- **The file names inside a sharded manifest's phase directory.** They are an
  implementation of the layout, reached through `_manifest_io`, not an interface.
- **That `/audit:migrate` can be undone.** It is documented as one-directional. It is
  also a *choice*, not an upgrade: a single-file manifest never goes out of date.
- **That an enum gains no members.** A new task status, a new gate name or a new
  branch type is additive, and code that switches exhaustively over one of them
  should have a default arm.
- **The CONTENTS of a cache block the plugin writes for itself.**
  `meta.ado.hierarchy`, `meta.ado.parentCandidates` and `meta.ado.connection` are
  cached *evidence*, re-derived by the `/audit:sync` subcommand that owns each one —
  so the block may gain fields, and a value inside it (which auth path answered, how
  a `basis` sentence is phrased) may be spelled differently in a later release. The
  promise that holds is the one every cache here already states about itself: each
  carries a `fetchedAt` and a `basis`, and deleting the block is always safe, because
  absent means "never fetched" and every reader is written to that. Do not build a
  tool on a cache's interior; re-run the command that writes it.

## 2. The config keys — `.claude/audit.config.json`

Every key is optional, unknown keys are accepted, and an absent file means the
documented defaults. `plugins/audit/schema/audit-config.schema.json` is where the
keys are published and the
[plugin README](plugins/audit/README.md#configuration-claudeauditconfigjson) is the
per-key table; `plugins/audit/scripts/config/_config_rules.py` is what actually runs,
and it is the authority when the three disagree. On **which top-level keys exist** they
can no longer disagree quietly: `_config_rules.config_vocab_drift()` compares that
module's key set against the schema's root properties, against the README's table and
against the hooks' own defaults, in both directions, and a gap fails the build naming
the surface and the key. Below the top level nothing compares them, so the promise
below stays phrased over **a key the plugin reads**, not over a list — the wording that
is still true of a nested key.

### Promised

- **A key a released version reads keeps being read.** Nothing you have written into
  this file stops working inside the major line. The precedent is already in the
  tree: `enforce` was superseded by `planGate` and is still honoured.
- **Absence keeps meaning the documented default.** Adding a key never changes
  behaviour for a config that does not set it, so an upgrade cannot alter what your
  repository does by introducing a lever you have not touched.

  **`portability` broke this promise once, on purpose, and that is why 2.0.0 is a
  major.** It ships as `"strict"`, which means a repository that has never written the
  key gets a control panel that offers only the skills a clone would load and refuses
  to write any other name into the plan — an edit that worked the day before the
  upgrade. Nothing about the manifest changes and nothing already written stops being
  read; what changes is what the panel will accept next. It was shipped strict rather
  than advisory because the defect it prevents is silent on exactly the machine that
  causes it: on the author's laptop every name resolves, so every warning tier reads
  as green there and the cost is paid by whoever clones. Set `"warn"` to keep the
  diagnosis and lose the refusal, or `"off"` to restore the previous behaviour
  exactly.
- **When two keys can express the same thing, which one wins is written down.**
  `planGate` beats `enforce`, and that precedence does not change without a major
  release. A superseded key is kept and documented, never silently reinterpreted.
- **When two keys COMPOSE rather than compete, that is written down too**, because
  a reader who finds only one of them draws the wrong conclusion. There is one such
  pair: `bashWriteCheck.enabled` and the plan gate both have to be permissive before
  the shell-write watcher's plan-coverage class says anything. `enabled: false`
  silences the hook outright; with it left on, that class still resolves a tier
  through `planGate` (and through the graded ladder when `planGate` is absent), so
  a repository with no manifest hears nothing from it. The watcher's other two
  classes — a write into a held manifest lock, a write into the audit journal — bind
  their claim to evidence of their own and report at every tier. Changing which of
  the two keys decides, in either direction, is a major release.
- **A malformed file does not take the guards down.** The hooks fall back to the
  documented defaults and warn once; the `/audit:*` commands refuse to run until it
  parses. Those halves differ on purpose — a guard that switches itself off because a
  config has a stray comma is worse than a guard on defaults, and a pipeline that runs
  against custom patterns which are silently not applying is worse than one that stops.

### Not promised

- **That a default value is frozen.** A default is a shipped opinion and may change
  in a minor release when the shipped value is wrong — the pricing table is the
  obvious one, and it is the reason every surface that renders a cost prints the date
  its rates came from. What is promised is that the *key* survives and that setting
  it explicitly wins. Pin what you care about.
- **That the capability policy resolves identically on two machines.** `policy` is a
  rule set, and a verdict is the rule applied to what is actually installed where the
  hook runs. Two developers can hold the same config and see different verdicts; that
  is the design, and `/audit:doctor` is what reports it.
- **That warning text is stable**, for the same reason as above.

## Outside this document entirely

Named rather than left ambiguous, because a promise without a boundary is not one.
None of the following is under the version contract, and depending on one is
depending on an implementation:

- the panel's HTTP endpoints and its page,
- the rendered report's HTML, its DOM and its Markdown twin,
- the audit trail's row shape, the usage ledger's NDJSON fields, and the evidence
  record's — all three are files this plugin writes and re-derives; the manifest's
  `testEvidence` block is the interface, and an evidence row is not,
- every file the hooks keep under `stateDir` — the session slots and the
  running-copy stamp. They are scratch a session writes and the next one replaces,
  garbage-collected after a week, and `/audit:doctor` reads the SHAPE of one of them
  on purpose: a slot missing a key this release writes is how it tells that the hooks
  in force came from an older copy. A promise that the shape held still would take
  that diagnosis away,
- the hooks' payload handling, and every exit code except the validators' — the CI
  verdict `/audit:status --gate` returns is a fair thing to want promised and is not
  promised here, so pin the plugin version if you wire it into a pipeline,
- **what a guard refuses, and the words it refuses with.** A guard narrows and widens as the
  failures it exists for are measured, and 2.1.1 did both: `require-plan` stopped exempting the
  manifest for subagents (narrower — a subagent that edited the plan now cannot), and Rule #1
  stopped reading a secret filename in prose as a read (wider — a body that merely names one now
  passes). Neither is a config key or a schema version, and a plan that depended on either
  behaviour was depending on an implementation. `SECURITY.md` is where the current posture is
  described and it is the document to read after an upgrade,
- **which FLAGS a verb accepts, when the verb never read them — and it changed.** One
  `argparse` parser serves all five verbs of `scripts/manifest/audit-task.py`
  (`/audit:task add|scope|cancel`, `/audit:phase add|retarget`), so every flag parsed on
  every verb while each verb's writer read only its own subset. Half the (verb, flag) pairs
  were therefore **accepted, wrote nothing for the flag, and exited 0** — `scope --outcome`,
  `retarget --files`, `add --id`, `add-phase --risk` among them. Those pairs now **exit 2**,
  naming the verb that does read the flag. **Nothing that ever took effect stops taking
  effect**: every refused pair is one whose value was already being discarded, so a caller
  whose exit code changed was already not getting what it asked for. It is recorded here
  rather than passed over because an exit code moved from 0 to 2 on a shipped command, and a
  pipeline that read a discarded flag as success is a pipeline that now stops,
- **the id `/audit:phase add` allocates when you do not pass `--id`.** It was the lowest free
  `P<n>` and is the **highest in use plus one**. The taken set is unchanged — live phases and
  every id a parked proposal reserves — and `--id` still overrides it. The old rule re-minted
  a number a finished phase had already used, and `meta.branch` derives a branch name from the
  phase id, so the id handed back could collide with branches and merges that already existed.
  A caller that predicted the next id from the plan will now predict a different one,
- **what a mutating command derives for you inside the manifest.** `--tests-add` carries a
  task's `tests.add` entries into its `files` (so the task's own commit passes
  `commit_scope`), and it now carries **the path an entry names** rather than the whole
  string — the field is documented as free prose, so what used to land in `files` was usually
  a sentence, and the permission the union exists to grant was never granted. An entry naming
  no file adds nothing and the command says which entries those were. Nothing already written
  is rewritten or stops being read; what changes is what the next `add` or `scope` derives.
  The half of F294 that **is** under the contract is the validator rule beside it, and it is
  recorded as a deprecation under *Validation stays additive* above rather than here — it
  warns from 2.3.0 and refuses at 3.0.0,
- `plugins/audit/reference/orchestrator.md` and the prose the model reads,
- every path under `plugins/audit/scripts/` — the plugin's own modules move, and
  `CHANGELOG.md` is where a move is recorded.

If you need one of these to be stable, say so in an issue; the answer is a promise
added here, not an assumption held quietly.

## How the promise is checked

A promise nothing checks is a sentence. These run on every push:

- `plugins/audit/scripts/manifest/validate-manifest.py` accepts both layouts, and CI
  validates two real manifests with it — the starter template, which is single-file,
  and this repository's own dogfooded plan, which is sharded. One release cannot
  quietly stop reading one shape.
- `plugins/audit/tests/test__manifest_io.py` pins the round-trip: a single-file
  manifest split into an index plus shards and reassembled is the manifest it started
  as.
- `plugins/audit/tests/test__manifest_rules.py` pins that `meta` keys from named
  earlier releases stay silent, and that an unrecognised key warns rather than fails.
- The config key sets are owned in one place, and the control panel's Settings
  coverage is **derived** from them rather than hand-listed — so a key the plugin
  reads has a control, or a declared exemption whose reason is itself pinned. That
  direction is held; the reverse one, a key that runs before it is published, is not,
  which is why the promise above is phrased over what is read.

## Reporting a break

If an upgrade stops reading a manifest or a config that a previous release read, that
is a bug in this plugin and not a migration you owe. Open an issue with the release
you came from, the release you went to, and the smallest file that reproduces it.
