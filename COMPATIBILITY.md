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

  **The `tests.add` path requirement was the first thing announced under this promise
  rather than excused from it, and the promise held through the whole 2.x line.** A task in
  `tests.mode: "tdd"` that is **not** `done` or `cancelled` must write each
  `tests.add` entry as `"<path>: <what it asserts>"`. **2.3.0** made an entry naming
  no file a **warning**, and its text named both the shape to write and the release
  the refusal would arrive in; **3.0.0** is that release — the entry is now a
  **finding**, and validation refuses it. Nothing that validated before 2.3.0 stopped
  validating inside 2.x — that was the promise, and the warning is what bought the
  time to act on it.

  **Why the interim was a warning and not a permanent softness.** The rule exists
  because of what the field is *for* at that mode: `/audit:task add` and `scope` put
  the path an entry names into the task's `files` precisely so `commit_scope` will
  allow the case file the task says it will create — and when the entry is prose
  there is no path to carry, so the permission was never granted and the task's own
  commit trips a scope the operator had just set. That was worth refusing, and 3.0.0
  refuses it. What a major release buys is the ORDER: announce, then enforce. A rule
  that only ever warns would be the softer answer this is not.

  **What the rule's shape bounds, and what it does not.** The schema stays
  permissive, so nothing about the field's *type* changed; `regression` and
  `gate-only` entries stay free prose, which is the shape most of them have; and a
  `done` or `cancelled` task is exempt, because its `tests.add` is a record of work
  already judged and a closed task's scope stays append-only — a line there would be
  permanent with no remedy. The repair for a live one is to name the file:
  `/audit:task scope <id> --tests-add "<path>: …"`.

  **And a plan written before the rule has a migration, which is what makes the
  announcement fair.** `plugins/audit/scripts/manifest/repair-tests-add.py <manifest>`
  reports every entry the rule reaches and, with `--apply`, rewrites the ones that
  already spell their path inside the sentence — putting that path in front and keeping
  the sentence whole. It will not guess one for an entry that names no file, or names
  several; those are listed with the task that holds them, because a wrong path in
  `files` is worse than a sentence. Announcing a refusal with no way through would
  strand every plan generated before it, which is the half of *announce, then enforce*
  that is easy to leave out. It runs on a manifest carrying only this finding, too:
  the finding this rule produces is excluded from the tool's own pre- and post-write
  checks, because refusing to touch precisely the plans it exists for would leave
  the announcement with no way through after all.

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

  **A bug value the published schema refuses is the second announcement, and it
  arrives the same way.** `validate-manifest.py` checked a bug's required fields, id
  pattern, status and links but never a value's *type*, while
  `schema/audit-plan.schema.json` types every bug property — so the plugin's own
  validator, which every verb and gate runs, accepted bugs the published schema
  refuses (`files: "src/a.ts"`, `severity: 3`, `description: null`). Such a plan
  validated under 3.0.1, and this promise is what it validated under. So in the 3.x line
  each such value is a **warning** naming the field, the type it has, the types the
  schema admits, and **4.0.0** as the release that refuses it; 4.0.0 makes it a finding.
  The types are read from the schema file at validate time, and its patterns are read
  the way `ajv` reads them (ASCII digits; `$` is the end of the string), so what the
  warning names is what the published schema says for every keyword the bug item
  uses. That covers the id too: an id ending in a newline or spelled with a non-ASCII
  digit passed the id check in 3.0.1, and that check keeps its reading; the
  schema's stricter one reaches it as this same warning. The warning buys the time:
  the repair is to write a value the schema admits, and nothing that validated before
  stops validating inside 3.x. Not under this announcement: a value a check that
  already existed refuses (a malformed id, a status outside the vocabulary, a
  non-integer `ado.id`) stays the finding it was, and the schema adds no second line
  about that path, though a different path beside it (an integer `ado.url`) is still
  its own warning; a schema the plugin cannot read at all is a finding from the
  command that loads it, because that is a broken install rather than a plan; and a
  schema keyword the validator does not interpret is at most a warning, because that
  fault is the plugin's — the build refuses to ship a schema whose bug item uses one.
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
- **A stored terminal phase status keeps winning, and `done` is also DERIVED.** A phase
  carrying `status: done` or `status: cancelled` reads exactly that. Otherwise it reads
  `done` once every task is terminal, `review.status` holds a sign-off verdict (`passed` or
  `skipped`) and, for a phase with a `branch`, `mergedAt` is set - which is what
  `/audit:phase signoff` and `close-phase.py` write between them. Each then also STORES the
  status it derives, and `/audit:task done` stores a linked bug's derived `fixed` and `fixedIn`:
  that is additive - a value the derivation already answered is now also written down, for the
  readers that do not derive - and it changes nothing about which value wins, because a stored
  terminal status and a person's `wontfix`/`not_a_bug` still win inside the derivation, so no
  write moves a value away from what the derivation answered before it. A stored value then no
  longer follows a later change to its inputs, so the paths that make one move it too:
  `audit-task.py reopen` refuses a task whose phase is signed off, and `repair-commits.py --apply`
  clears a `fixedIn` holding the commit it clears. A plan carrying the
  older, stale values keeps reading correctly through the derivation; `validate-manifest` warns
  about them (a warning, never a finding) and `audit-task.py settle` stores them. Reversing that
  precedence, or ceasing to read a verdict as sign-off, is a major. What is not promised is the
  wording surfaces use for the state in between ("sign-off due"), under the standing exclusion
  for a command's wording below.
- **`meta.phaseGate` and `meta.gateBudgetMs` are under the same promise, and absence keeps
  meaning today's behaviour byte-for-byte.** With no `meta.phaseGate` at all, a new phase's
  default gate is every `meta.buildCommands` key, in `buildCommands` order — exactly what
  `/audit:phase add` wrote before either key existed. `phaseGate.always` alone only REORDERS that
  default, putting the named keys first; it drops nothing on its own. With no `phaseGate.exclude`,
  nothing is dropped from the default either. With no `meta.gateBudgetMs`, nothing is graded on
  cost — `/audit:doctor`'s gate-economy row says so as an OK, never as silence. **A task's derived
  gate reading `meta.phaseGate.always` when its own files name no suite to narrow to
  (`tests.gateBasis: gate-only-no-suite`) moves no promise on this list either**: a NEW task's
  derived gate has never been a promised value — only a manifest key a release *reads* is, and
  the derivation this adds is one more shape that reading takes.
- **`meta.phaseGate.mode`, `meta.coupling`, `phase.testGateDerived` and `phase.testGateBasis` are
  under the same promise, and each absence is its own documented reading, never a gap.**
  **`mode` absent means no PHASE-level derivation is ever computed** — `always`/`exclude` alone
  still shape the wide gate exactly as they did before either key existed, and no narrower gate
  is ever asked for. **`meta.coupling` absent means no learned arm contributes** — a derivation
  still runs on `tests.add`, the import-graph listing, changed files and the last recorded
  failure alone, which is exactly today's behaviour for a plan that has never coupled a test to
  a source by hand. **`phase.testGateDerived` absent means `run-test-gate.py` prints no NARROWED
  line and grades no derived-mismatch `could-not-run`** — a run against a phase that has never
  derived a gate reads exactly as it did before either key existed. **`phase.testGateBasis`
  absent means the undeclared default** — the same reading `tests.gateBasis` carries at task
  scope: nothing has narrowed the gate and there is no reason string to read.
  `derive-phase-gate.py` writes `testGateBasis` together with `testGateDerived`, so the two
  are absent or present as a pair. Ceasing to read any of the
  four, or reversing what its absence means, is a major.
- **`meta.fullGate`, `phase.mergedHead` and `phase.mergedHeadAt` are under the same promise,
  and each absence is its own documented reading, never a gap.** **`meta.fullGate` absent means
  this plan names no third place at all** — no phase is ever provisional for lack of one,
  `run-test-gate.py --full` refuses rather than measuring nothing, and the
  `provisional`/`stale-full-run` status conditions are inert on every surface that grades them.
  **`phase.mergedHead` absent means ancestry cannot be asked at all**, so a merged phase reads
  `unknown` rather than `provisional` — a specific gap this plan has no way to measure is never
  claimed in its place. **`phase.mergedHeadAt` absent means `mergedHead` is the recovered
  commit** described next, and `stale-full-run` measures from `mergedAt`; present, it means
  `mergedHead` was recorded after the fact, and `stale-full-run` measures from it instead.
  `phase.mergedHead` is written into a plan only by `close-phase.py` (the demo generator stamps
  its own fixture); a plan that never adopts the third
  place behaves exactly as it did before any of the three existed. Ceasing to read any of them,
  or reversing what its absence means, is a major.
- **`phase.mergedHead` keeps two readings, and `phase.mergedHeadAt` keeps telling them apart.**
  Without `mergedHeadAt`, `mergedHead` reads as the commit recovered from the parent's
  first-parent chain as the one that brought the phase branch's tip in. With `mergedHeadAt`, it
  reads as the parent's head at that moment, recorded with the branch gone and held to every task
  commit the phase records — and nothing more is proved: a wrong parent that holds every recorded
  task commit passes that check, and it says nothing about work no task recorded. What is
  promised is the pair of readings and which key selects one — never which commit a given close
  will find.
  **The caveat is historical, and it is narrow.** No released version wrote `mergedHead` at all
  (the key first appears under *Unreleased* in `CHANGELOG.md`), but a plan written by an
  unreleased build from before `mergedHeadAt` existed may carry an unmarked `mergedHead` that is
  the parent's head at close time rather than the recovered commit, and `close-phase.py` never
  replaces a head already recorded.
- **`meta.muted` and `meta.coupling[].lastCaught` are under the same promise, and each absence
  is its own documented reading.** **`meta.muted` absent means nothing is quarantined** — every
  failing step fails the run exactly as it did before the key existed. **`lastCaught` absent
  means the coupling has not been caught since it was learned**, so `/audit:doctor` ages it from
  its `learnedAt`; `lastCaught` is written only by `audit-task.py couple --caught`, never moved
  back to an earlier moment. Ceasing to read either, or reversing what its absence means, is a
  major.
- **An expired mute is a warning, never a finding.** Every mutating verb refuses a plan that
  already carries a finding, and the default status gate fails on one, so a finding triggered by
  a date would freeze every verb — including `unmute`, the verb that lifts it — and fail every
  default CI gate on the morning the mute expires. The enforcement is the runner, which stops
  honouring an expired mute so that failure blocks again on its own. A mute naming no bug in
  `bugs[]` is a finding from the moment it is written. Turning expiry into a finding is a major.
- **The `provisional` and `stale-full-run` status conditions are opt-in, and `DEFAULT_GATE` is
  unchanged by their addition.** `--fail-on` is what turns either on; a plan that has never
  declared `meta.fullGate` or recorded a full run fails no build over a condition it never
  asked for.
- **`unknown-full-run` is an additive `--fail-on` condition, outside the `--gate` default.** It
  trips on a merged phase whose full-run answer is `unknown` — no `mergedHead` recorded, git
  unable to answer ancestry, or a ledger that could not be read — and no existing gate changes
  verdict by its addition: `DEFAULT_GATE` does not hold it, `provisional` still never counts an
  `unknown` phase, and a plan with no `meta.fullGate` never trips it.
- **The evidence row's `outcomeBasis` and `derivedGap` step keys are additive.** A row written
  before either existed carries neither key, which is the true reading for it, and a passed
  step's row is unchanged.
- **A ledger written before the evidence rows were hash-chained keeps verifying.**
  Rows now carry `prev` and `hash`; rows written by an earlier release carry neither,
  and `audit-journal.py verify` reports those as a **counted warning naming what is
  unprotected — never as tampering**, so upgrading does not turn a project's record
  red. That grading is the promise, not the row shape: what is *not* promised is that
  the two keys keep their spelling, and what stays a finding either way is an
  unchained row appearing *after* a chained one in the same file, since without that
  the chain would be opt-out. The verdict a record reaches is the thing to depend on;
  the bytes it reaches it from are not.

### Not promised

- **That newer releases add no keys.** They will. Your reader must tolerate keys it
  does not recognise, exactly as the plugin tolerates yours.
- **Forward compatibility.** A manifest written by a newer release loads on an older
  one because unknown keys are tolerated — it is not *promised* to, and the older
  release will not act on what it cannot see. The promise runs one way: forward in
  time, never backward.
- **The text of findings and warnings.** They are prose for a reader — on the terminal
  and inside a `--json` block alike, and the block's grouping of them is prose too.
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
- **That an older plugin reads an id a newer one mints.** From the release that
  introduced branch-suffixed ids (`BUG-12-k7m`), those ids validate, and every id an
  earlier release minted still does - the widening is additive. An EARLIER plugin's
  validator refuses a suffixed id, so a team upgrades together rather than one clone
  at a time.
- **Nothing about undoing a layout change beyond what `/audit:layout` does.** It moves
  in either direction (`/audit:migrate` is its old name). A layout is a *choice*, not
  an upgrade: a single-file manifest never goes out of date.
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

  **`review.perTask` breaks this promise a second time, and ships in a minor release
  by the maintainer's decision** — a recorded exception to the rule that a changed
  default is a major. It ships as `"phase"`, which means a repository that has never
  written the key no longer has a reviewer run per task: `audit-task.py done --commit`
  records the task's intent as `deferred` and refuses every `--intent` word (a fix task
  `add --fixes` recorded closes only `not-asked` with its basis); the phase review
  answers each task at sign-off, in a `tasks` array it files with `file-return <phaseId>
  --role reviewer --head <sha>`; and `/audit:phase signoff` — under `--verdict skipped`
  as under `passed` — and `close-phase.py` at its own merge refuse while a task that
  records a commit lacks its three answers bound to that commit. `close-phase.py` asks
  the plan it is handed, the copy on disk in the worktree holding the branch and the copy
  the branch tip carries in; it refuses a tip whose copy records no sign-off verdict, and
  one whose copy it cannot read when the plan is versioned (inside the git root, not
  ignored, committed at the parent or at `baseRef`) - a plan git never commits is asked
  through its copy on disk. Sign-off, by the driver or by hand, also refuses while a
  filed phase return holds a `diverges`, `cannot-tell`, `not-proved` or `flagged` answer
  the driver's `--answer accept --reason` has not settled, and that stop on a phase intent
  holds under every `review.perTask` value. So does `close-phase.py`'s: under every
  `review.perTask` value it refuses to land a phase whose filed phase return - on disk,
  in the worktree holding the branch, or at the branch tip - holds such an answer, or
  will not parse, while the tip's copy of the plan records no sign-off verdict (the copy
  on disk, for a plan git never commits). A recorded verdict settles only the returns
  its own checkout's sign-off read: a tip's verdict, the returns the tip commits and the
  ones in the worktree holding the branch; a verdict on a copy on disk, that checkout's
  own. A return holding such an answer found anywhere else - in the parent checkout's
  evidence directory, whose copy of the plan shows the phase as at the fork, so
  `file-return <phaseId>` run there accepts it after the branch signed off - is refused,
  filed before the verdict or after it; in an `evidence.dir` both checkouts share, only
  an answer the worktree's driver settlement names is settled. `file-return <phaseId>`
  refuses a phase return only where the copy of the plan it reads records a sign-off
  verdict. A task that no longer records its commit, a merge made by hand
  or through a pull request, and who filed the phase return are outside that refusal;
  the plugin README's followed table names each, with the evidence left afterwards. A phase already under way when the plugin is
  upgraded reads the new default too, unless it recorded a `reviewPerTask` value, which
  no older copy wrote — so its tasks closed by a per-task reviewer are owed the phase
  review's answers before it lands. It was shipped as the default because a reviewer per
  task is a cost paid on every task that a plain session does not pay
  (`docs/research/pipeline-cost-design.md`, C14), and every answer the per-task review
  gave is still given, bound to the same commit; what moves is when, before the merge
  instead of before the commit. Set
  `"always"`, before upgrading if a phase is in flight, to restore a reviewer per task. It
  does not restore the previous behaviour exactly: a close under `always` is still held to
  the filed-return rule in *closing against a commit with no review behind it* below, and
  `start`, `done` and `signoff` refuse a `review.perTask` value outside the vocabulary
  wherever neither the task nor its phase records a key.
- **When two keys can express the same thing, which one wins is written down.**
  `planGate` beats `enforce`, and that precedence does not change without a major
  release. A superseded key is kept and documented, never silently reinterpreted.
  **The price table** is the second such pair, and the manifest is party to it: the plan's
  `meta.usage.pricing`, when it declares a non-empty table, beats the config's
  `usage.pricing`, and either beats the shipped table. A declared table is laid over the
  shipped one model by model, so a model it does not name keeps its shipped row. Every
  surface that prints a cost takes that one answer (`usage_ledger.resolve_pricing`); the
  meter and the panel read only the config before this order was written here.
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
- **the merge driver's name, its shim and how the record merge resolves a case** —
  what `/audit:layout merge-driver install` writes into `.gitattributes`, git config
  and the git dir. The driver is a convenience over files the promise already covers,
  and it is built to fail towards git's own behaviour: a clone whose configuration no
  longer names what `.gitattributes` names gets git's line merge with markers, never
  a silent result. Re-run `install` after an upgrade that renames anything,
- the rendered report's HTML, its DOM and its Markdown twin,
- the audit trail's row shape, the usage ledger's NDJSON fields, and the evidence
  record's — all three are files this plugin writes and re-derives; the manifest's
  `testEvidence` block is the interface, and an evidence row is not. The block's
  `gradedBy` (a group member's copy of its carrier's pointer) and a phase review's
  `noEvidenceReason` and `acceptedCommits` are additive keys; a manifest without them
  validates and reads exactly as before,
- **the audit trail's file names.** A journal or evidence file is named by its month
  and its writer, and the writer has already been refined once: a linked worktree
  (git's answer, asked where `gitRoot` points) writes `<month>.<session>.wt-<key>.jsonl`
  beside the session-keyed name a main checkout keeps, the key held in that worktree's
  own git dir. The limit that remains: when git cannot be asked, or the key cannot be
  stored in the worktree's git dir, the session-keyed name is used and two worktrees
  of one session can share it again. Every name an earlier release wrote is still read
  — every reader walks the directory — but a tool that builds a name itself instead of
  listing the directory is depending on an implementation,
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
- **a `passed` sign-off with no gate run behind it — and it changed.** `audit-task.py
  signoff --verdict passed` (`/audit:phase signoff`) used to write the verdict whatever the
  ledger held; it now **exits 2** unless the phase's newest recorded gate run binds its work,
  or `--no-evidence-reason "<why>"` is passed and recorded. Unlike the flags entry above,
  something that used to take effect now does not: a pipeline that signed off without
  recording a gate run is a pipeline that now stops, and the repair is the gate run or the
  reason. `close-phase.py`'s refusal for a phase that records no branch and whose composed
  name is not one moved from **exit 4 to exit 1**: git answered, and the command is what has
  to change (`--branch`),
- **closing over a verdict that no longer holds — and it changed.** `audit-task.py done` and
  `close-phase.py` used to exit 0 closing a task or landing a phase whatever its newest recorded
  gate verdict said; each now refuses instead — `done` exits 2, `close-phase` exits 1 — naming
  the verdict that no longer holds, **except** where there is no verdict to vouch for: no run is
  recorded under the gate, the newest row answers `empty-gate`, the phase's branch has already
  landed, or the newest green is stale behind a sign-off's `--no-evidence-reason` — none of those
  refuse, and closing proceeds as before. The refusal takes `--override-verdict "<why>"`, which
  journals `audit.verdict.close-overridden` and closes anyway — unless the override itself cannot
  be recorded: with `journal.enabled` false, `done` still exits 2 and `close-phase` still exits 1
  rather than closing with the exception nowhere written down; if the journal row fails to write,
  `done` rolls back and exits 1 instead of 2, and `close-phase` exits 1 having merged or written
  nothing. A sign-off given no `--no-evidence-reason` now drops an earlier phase review's
  `noEvidenceReason` (the same additive key named above) rather than letting it outlive the
  sign-off that recorded it. A pipeline that closed over a red gate is a pipeline that now stops,
  and the repair is a green run or the override,
- **closing against a commit with no review behind it — and it changed.** `audit-task.py done
  --commit <sha>` used to close whether or not a reviewer had answered: with `--intent matches`
  typed by the caller, or with no `--intent` at all, recording no answer. Every close that
  passes `--commit` — with or without `--from-return` — now **exits 2**, writing nothing,
  unless the reviewer's return is filed for the task's current start (`audit-task.py
  file-return <taskId> --role reviewer`), whose answer is then the one recorded; a typed
  `--intent` that differs from that filed answer is refused too, `not-asked` included. A
  close typed by hand with no review behind it now has to say so: `--intent not-asked
  --intent-basis "<why>"`. A `--no-change` close is unchanged. The filed return, its
  directory under the evidence directory and its shape are a new record outside the contract;
  `--from-return` and `file-return` are additive. A pipeline that closed with a typed or a
  missing intent is a pipeline that now stops, and the repair is the filed review or the
  stated `not-asked`,
- **signing off a phase as `skipped`, under `review.perTask: phase` — and it changed.**
  `audit-task.py signoff --verdict skipped` used to sign off with neither a gate run nor a
  reason. Under `review.perTask: phase` (the shipped default, above) it now **exits 2**,
  writing nothing and naming each task, while a task of the phase with a commit lacks the
  phase review's three answers bound to that commit, exactly as `--verdict passed` does; the
  group form asks every member before writing any. `close-phase.py` asks the same of the
  plan's record and **exits 1** before it merges or hands over the merge command. A phase
  with no task whose key reads `phase` signs off and lands as before. The `tasks` array a
  phase return carries, `intentCheck`'s `deferred`, `redFirst` and `inheritedTests` fields,
  and the `reviewPerTask` and `fixes` fields are additive,
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
  The part of this change that **is** under the contract is the validator rule beside it, and it is
  recorded as a deprecation under *Validation stays additive* above rather than here — it
  warns from 2.3.0 and refuses at 3.0.0,
- `plugins/audit/reference/orchestrator.md` and the prose the model reads,
- every path under `plugins/audit/scripts/` — the plugin's own modules move, and
  `CHANGELOG.md` is where a move is recorded,
- **coordinating more than one repository.** A manifest governs the repository
  that carries it. There is no cross-repo view, no shared lock and no combined
  report across two projects, and none of that is planned — pointing a second
  project's config at the same plugin gets a second, independent set of guards,
  never a shared one.

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
