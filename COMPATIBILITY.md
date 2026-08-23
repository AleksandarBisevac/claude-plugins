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
- **The file names inside a sharded manifest's phase directory.** They are an
  implementation of the layout, reached through `_manifest_io`, not an interface.
- **That `/audit:migrate` can be undone.** It is documented as one-directional. It is
  also a *choice*, not an upgrade: a single-file manifest never goes out of date.
- **That an enum gains no members.** A new task status, a new gate name or a new
  branch type is additive, and code that switches exhaustively over one of them
  should have a default arm.

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
- **When two keys can express the same thing, which one wins is written down.**
  `planGate` beats `enforce`, and that precedence does not change without a major
  release. A superseded key is kept and documented, never silently reinterpreted.
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
- the audit trail's row shape and the usage ledger's NDJSON fields,
- the hooks' payload handling, and every exit code except the validators' — the CI
  verdict `/audit:status --gate` returns is a fair thing to want promised and is not
  promised here, so pin the plugin version if you wire it into a pipeline,
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
