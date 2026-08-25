---
description: 'Sync the audit manifest with Azure DevOps work items — set the connector up for the first time (connect: verify the transport, report which auth path is in effect, prove access read-only, detect the board''s process), push manifest bugs/tasks/phases to ADO (board states, sprint stamp, Remaining Work, comments), pull assigned ADO bugs or sprint items into the manifest, or show link status. Explicit, idempotent, one direction per invocation; configured via meta.ado.'
argument-hint: 'connect | push [bugs|tasks|all] [--task <id> | --phase <id>] | pull [bugs|sprint] | parents | status'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__azure-devops__wit_*, mcp__azure-devops__work
---

# /audit:sync — Azure DevOps work-item sync

Mirrors the manifest's `bugs[]`, tasks and (via `phaseWorkItems`) phases into Azure
DevOps work items and back. **No background magic**: every invocation does exactly one
direction, shows its plan, and is idempotent (re-running converges; nothing duplicates).
The orchestrator additionally **echoes** already-linked items on status transitions
(update-only — see `orchestrator.md` → "ADO echo"); this command is the reconciler that
heals whatever the echo missed.

**`$ARGUMENTS`**: first token is the subcommand — `connect`, `push`, `pull`, `parents`
or `status`. Unknown/empty → print usage and stop.

**`connect` is the one that runs before `meta.ado` exists**, so Preflight 2 below does
not apply to it: it is how the block gets written. Every other subcommand still stops
without one.

## 0. Preflight

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` and
   `${CLAUDE_PLUGIN_ROOT}/reference/tracker-sync.md` (the shared contract + the ADO
   binding: field reference names, state fallback, parent links, iteration resolution).
   Resolve and read the manifest. Missing → stop, point to `/audit:init`.

   **The manifest may be SHARDED, and then the file at `manifestPath` is an INDEX
   whose phases are stubs** — the tasks, and every `ado` link on them, live in the
   phase shards beside it. A plain read of that file is therefore not a read of the
   manifest: it finds the bugs' links and none of the phases' or tasks', and reports
   the difference as *unlinked* rather than as unread. Nothing errors; the number is
   simply smaller. Every script below goes through `_manifest_io.load_manifest`, and
   the counts and links this command would otherwise walk itself come from
   **`read-ado-links.py`** (step 2 of `status`). No step in this file wants the raw
   file, so if you are about to `Read` the manifest to count something, that is the
   door to run instead.
2. **`meta.ado` must exist** — else stop and point at **`/audit:sync connect`**, which
   verifies the transport, reports which auth path is in effect, proves access with a
   read-only query and detects the board's process before writing the block. Print the
   snippet too, for anyone who would rather write it by hand:
   ```json
   "ado": { "organization": "<org>", "project": "<project>",
            "areaPath": null, "iterationPath": null,
            "types": { "bug": "Bug", "task": "Task" } }
   ```
   (The v2 keys — `stateMap`, `sprint`, `pull`, `onComplete`, `comments`, `echo`,
   `phaseWorkItems`, `enabled` — are optional; the panel's ADO card edits them all.)
3. **`meta.ado.enabled: false` disables writes**: `push` and `pull` STOP with
   `connector disabled — re-enable in the panel's ADO card (or set meta.ado.enabled)`;
   `status` still runs (read-only is the drift lens you need to decide whether to
   re-enable) and leads with `connector DISABLED — N linked item(s) frozen, links kept`.
4. **Transport**: if `mcp__azure-devops__wit_*` / `mcp__azure-devops__work` MCP tools
   are available in this session, you MAY use them (same field mapping below).
   Otherwise use the `az` CLI via Bash:
   `az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>`
   then `az boards ...`. If `az` is missing or the `azure-devops` extension isn't installed,
   STOP with install guidance (`az extension add --name azure-devops`; auth via `az login`,
   or the `AZURE_DEVOPS_EXT_PAT` environment variable in CI).
5. **Credentials are never yours to handle**: never write a PAT/token into the manifest,
   the config, or any file; never echo one (the secret guard blocks it anyway). Auth
   belongs to `az` / the MCP server.
6. After EVERY manifest mutation: revalidate with
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>`.
7. `push`/`pull` write the manifest — hold the **concurrency lock** (see conventions →
   Concurrency lock) around those writes; `status` is read-only and never locks.

## Every ADO call is bounded, and says so when the bound expires

**A hang is worse than a failure.** A failure names what happened and what was
written; a hang says nothing at all, and the operator cannot tell a slow board from a
dead one, an expired credential from a firewall, or a run that is still working from
a run that will never finish. `status` is the worst case, because it advertises
itself as safe and read-only — so it is the one people leave running.

Every rule below applies to **every** ADO call this command makes, on both
transports, in every subcommand.

1. **Give each call an explicit time bound** — the `timeout` on the Bash invocation
   itself. Not a `timeout <n>` prefix inside the command: that is GNU coreutils and a
   stock macOS has neither `timeout` nor `gtimeout`, so wrapping it would be an
   instruction that silently does nothing on the platform this was reported from.
   Per CALL, not per run:

   | Call | Bound |
   |---|---|
   | one work-item read or write (`work-item show` / `create` / `update` / `relation`) | 30s |
   | one batch query chunk | `fetch-ado-items.py` owns it — `--dry-run` prints the default, `--timeout` overrides |
   | project metadata (`devops invoke` backlog configuration, iteration resolution) | 30s |

   The basis for those, and the reason they are generous rather than tight: a single
   round trip against a live board measured well under two seconds each way
   (tracker-sync.md → live-gate F5, which carries the probe). A call that wants more
   than an order of magnitude beyond that is not slow, it is stuck.

2. **Name the outcome on expiry.** Print
   `ADO TIMEOUT: <which call> did not answer within <N>s` followed by **what was and
   was not written** — for `status`, `nothing was written; this table is incomplete`;
   for `push`, the items already created or updated by id, because the manifest links
   for those are already on disk. Then STOP that subcommand. Never retry silently and
   never carry on with the rows you happen to have: **"the board returned no items"
   and "the board did not answer" are different answers**, and only the first one is
   safe to act on. A drift table missing the half that timed out reads as a clean
   board for that half.

3. **Make a credential prompt an error rather than silence.** Give every `az` call
   `--only-show-errors` — the CLI's upgrade and extension notices go to stderr on
   every call, and suppressing them is what leaves a real `ERROR:` line legible there
   rather than buried; stdout was always the JSON alone — and redirect stdin from
   `/dev/null` so nothing can sit waiting for a token to be typed. `az boards` with
   no stored credential already exits non-zero
   naming `az login` / `az devops login` rather than prompting, which is the behaviour
   wanted; the redirect is what keeps that true of any call that would prompt.

4. **The MCP transport gets the same bounds and the same named outcome**, applied to
   the tool call. It has no `--only-show-errors` and no stdin to redirect, so rule 3
   is `az`-only; rules 1 and 2 are not.

## Field mapping (both transports)

| Manifest | ADO (defaults; types from `meta.ado.types`) |
|---|---|
| bug → work item type | `types.bug` (default `Bug`) |
| task → work item type | `types.task` (default `Task`) |
| phase → work item type (`phaseWorkItems`, absent = on) | `types.pbi` (null = auto-detect, see tracker-sync.md) |
| `bug.title` / task: `[<taskId>] <title>` / phase: `[<phaseId>] <title>` | Title |
| `bug.description` + `repro` + `expected`/`actual` | Repro Steps (Bug) / Description |
| `bug.severity` high/med/low | Severity `2 - High` / `3 - Medium` / `4 - Low` |
| bug / task / phase status → **State**: not a row you translate here. `read-ado-links.py` owns `meta.ado.stateMap` over the built-in defaults and prints the target state per item **with the basis that produced it** | State (a `blocked` task also gets the tag `blocked`) |
| task `done` + `meta.ado.onComplete.remainingWork` (default 0 when `onComplete` present) | `Microsoft.VSTS.Scheduling.RemainingWork`, same update call — stock processes REFUSE it (they force-clear the field at done) → retry state-only, report the skip (tracker-sync.md) |
| `meta.ado.areaPath` (when set) | Area |
| resolved sprint (`meta.ado.sprint`) else `meta.ado.iterationPath` (when set) | Iteration |
| `meta.ado.fields.<work item type>` (when set) | those fields verbatim on CREATE — merged by `check-ado-item.py` **before** the conformance gate, so a board that requires e.g. `Microsoft.VSTS.Common.Activity` can be satisfied; a field this table already maps, or one ADO reports read-only, is refused at validation |
| always | provenance tag from `meta.ado.tag` (absent = `audit-plugin`; null = none) — tag writes READ-MERGE-WRITE the item's tag list, never wholesale; comment with `fixedIn` SHA when a bug closes |

## The state translation is a door, not a table you apply

**This file used to carry the map** — a status column, an ADO-state column, and an
instruction to translate. Two readings of it went wrong at once, and neither showed
up as an error. `status` step 3 was never told to apply it, so every drift row read
`state not compared (no mapped state supplied)`; and nobody applies
`effective_bug_status` from prose, so a bug whose fix task is done would have been
translated from its stored `open` and reported the board's `Resolved` card as ours to
overwrite. **A table in prose has to be applied by a reader, and that is the part that
cannot be tested.** So it is code:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/read-ado-links.py" <manifest> \
  [--items <fetched.json> --out <mapped.json>] [--json]
```

With no `--items` it prints the manifest side: linked vs unlinked per kind, then one
row per link — `kind | manifest id | ado id | status | state | basis`. With
`--items` it stamps `mapped` onto the payload `fetch-ado-items.py` wrote and writes
`--out`, which is the file the drift door must be handed. Exit 0 = answered. **Exit 1
= entries were given and not one of them could be given a state**, so every reading
downstream has no basis — including the overwrite count the confirm gate reads, which
is zero for that reason alone. Exit 2 is unreadable input, and `--items` without
`--out` is refused rather than treated as a preview.

**An entry it could not stamp is passed through and NAMED, never dropped** — a
shorter payload reads downstream as a board with fewer cards. The ways that happens
each carry their own word in the report: no manifest item links to that work item; the
transition is configured `null`; nothing maps that status at all; or **two manifest
items claim the same card and mean different states**, which the door refuses to
break rather than stamping whichever it walked into first. Nothing validates that a
work-item id is claimed once, so that last one is a real manifest defect to go and
unpick, and it is reported on both invocations.

Do not re-derive any of it here, and do not reconstruct a state from the report: a
second copy of that map is a second answer, and the first thing to disagree would be
somebody's board.

A `stateMap` value of `null` = **never move state for that transition** — the door
prints `never` for that row, skip the State field, the team moves that card by hand.
**States are applied by UPDATE, never at create** — ADO allows only the initial state
at creation (tracker-sync.md → "States are applied by UPDATE"), so every non-initial
target is a second call after the create. A state the process rejects degrades per
item (retry without State, report, hint at `stateMap`) — tracker-sync.md →
"Invalid-state fallback". The built-in defaults name Agile-process states, which the
door says on every row that used one; Scrum projects set `stateMap` (`connect` says so
from the process it detected, and doctor carries the advisory). Phase-item
vocabularies differ — a Scrum PBI knows no "In Progress" (tracker-sync.md).

The manifest side of a link is the item's `ado` field — `{id, url, lastSyncedAt}`
(plus `iterationPath` on sprint-stamped items) — **written only by this command and
the orchestrator echo's `lastSyncedAt` bump**, immediately after each successful
create (so an interrupted run resumes idempotently).

## Sprint resolution (shared by push and pull)

When `meta.ado.sprint` is set: resolve the team's CURRENT iteration ONCE per run
(tracker-sync.md → "Current-iteration resolution"); stamp `System.IterationPath` on
creates/updates, and record the stamped path on each touched item's
`ado.iterationPath` (phases included). Resolution failure → ONE warning, fall back to
static `meta.ado.iterationPath` (or no stamp), continue — never abort over a sprint.

## Identity mapping (`meta.ado.identityMap`, advisory)

`meta.ado.identityMap` is an OPTIONAL map from a **ledger identity** — the same form
`usage.authorMode` records authors and `meta.areas[*].owner` is written in (git
`user.email` under the default `email` mode, `user.name` under `name`) — to that
person's ADO identity (email/UPN). The ledger identity is the KEY because it is the
identity this plugin already owns: the usage ledger's author column, area owners and
this map are one namespace, and ADO is the foreign side being mapped to. Advisory
only: nothing in this command gates, refuses or assigns on the map by itself — push
PROPOSES, pull LABELS, status DISPLAYS, and an absent/null/empty map degrades every
flow below to exactly today's behavior. ADO identities compare **case-insensitively**
wherever this command matches them (ADO's directory does).

## Subcommand: `connect`

**The guided path to a first working connector.** Everything below is READ-ONLY except
step 5, which writes to the manifest and to nothing else. It creates no work item,
updates none, and touches no credential: auth belongs to `az` / the MCP server, and
after `az devops login` the credential already lives in the CLI's own store, so there is
nothing here to capture. **Never ask for, echo, copy or store a token** — the secret
guard blocks it anyway, and this command has no reason to want one.

It exists because the first thing that used to PROVE access was a `push`, which is also
the first thing that can CREATE items on somebody's real board.

**Do not re-derive any rung here.** `ado-connect.py` owns them, it prints the report
verbatim, and a second copy in prose is a second answer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/ado-connect.py" \
  <manifest> [--transport mcp] [--org <org> --project <project>] [--probe <file.json>] [--json]
```

Exit 0 = the ladder got as far as it can — with `--probe`, a plan to confirm. **Exit 1 = a
rung stopped it**: print what it said and stop, do not go on to a board call or a write.
Exit 2 is unreadable input, and is never read as a pass.

### 1. Transport, and 2. identity — one call, no arguments beyond the manifest

Run it with no `--probe`. It reports the transport it found and stops on its own rung when
there is none (`az extension add --name azure-devops`, or install azure-cli). Pass
`--transport mcp` when this session carries the `mcp__azure-devops__*` tools — then a
missing `az` is not a stop, and the identity is the MCP server's, which the command says
rather than guessing at.

**What rung 2 is for, and the trap it removes.** It reports which auth path is in effect
*for this organization*, from three things that are not secrets: whether
`AZURE_DEVOPS_EXT_PAT` is SET (never its value), the Azure sign-in `az account show`
prints, and the organizations `az devops login` has stored a PAT for. Stored credentials
are **per-organization** — measured: on one machine `uptimize` resolved through a stored
PAT while `test-audit-lab` resolved through the Azure sign-in, at the same moment.

When more than one path is present, **it says so and picks none**, because nothing
observable from outside says which one `az` answered with. The sentence that holds either
way is the one this rung exists for and the one to repeat to the user: **a board command
that succeeds proves the ORGANIZATION is reachable, never which identity reached it.**

It also states the **PAT scope this connector needs, and nothing else: Work Items → Read &
write.**

### 3. and 4. The probe, which is one query read two ways

The command prints the exact query. Make it — through `az`, or through the MCP tools if
that is your transport — then hand back an envelope, **the same shape whether it worked or
not**:

```json
{"exitCode": 0, "stderr": "", "rows": [ ...the query's JSON... ]}
```

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/ado-connect.py" <manifest> --probe <envelope.json>
```

It is a **Work Items** query deliberately: that is the only scope this connector needs and
the only one a careful person will have granted, so probing with `az devops project list`
would report a false failure on a PAT scoped exactly right.

**Two failure texts, and the one that misleads.** A project name with a typo in it answers
"The project specified is not found in hierarchy" — the credential worked. A *nonexistent
organization* answers **"you need to run the login command"**, identically to a real
credential failure (measured). The command grades that text as one verdict naming both
readings; do not turn it into "log in again" on your own.

The same rows answer rung 4. The **type** is the discriminator, not the states: measured on
the lab's Agile board, `User Story` was present while the Task states in use were only
`New` and `Closed`, because nothing was sitting in `Active` or `Resolved`. So observed
states are corroboration and never proof, and the report says which of the two each line
is. From the process it proposes `types` (`.pbi`, `.bug`, `.task`) and says **whether
`stateMap` is needed** — the built-in defaults name **Agile** states, so a Scrum board must
set one or a task reaching done is refused its state.

An **empty project**, a board with **no phase-level item yet**, and a customised board
carrying **two** are three different "not detected" answers, none of them a failure and
none of them a reason to guess: `types` is then simply not proposed.

### 5. The write — the only step that writes, and it asks first

**Print the door's PLAN block verbatim, as its own block above the question.** The
command composed it already: the head line `PLAN - <configured or not>: N to set, M to
change, K already right.`, then one `set` / `CHANGE` / `keep` row per key, then the
`restamp (not counted above)` line for the evidence block. **Paste those lines — do not
re-render them, and do not fold them into the AskUserQuestion's option text.** An option
label can carry a small plan and cannot carry a large one, and the day it is large is the
day a reader most needs the shape stated rather than narrated. The counts are printed by
the door **even at zero**, so a plan with nothing to do says so instead of leaving it to
be inferred from silence.

This is not a hypothetical: `connect`'s first live use reached its confirm with no plan
block above it, and the counts a reader sizes a write by existed only inside an option
label. A second rendering is a second answer, and here the first thing to disagree would
be how much the operator thought they were approving.

**The DECLINE consequence is printed too, and it is not yours to word.** The block ends
with a `decline` line saying exactly what not writing costs — and on a first connect that
is *nothing to fall back on*, because no evidence has ever been stamped. Paste it as the
declining option's text. It used to be absent, and what filled the gap was the apply
line's own wording: that line claimed unconditionally to replace "the last run's"
evidence, so a first connect was offered a choice between overwriting a moment that did
not exist and preserving it. Both halves of that question were false, and the door is now
the only thing that answers either.

Then **confirm via AskUserQuestion before writing** — this turns on an outward-facing
connector. Then, under the concurrency lock, apply it to `meta.ado`:

- `organization`, `project`, `enabled: true`, and `types` when a process was detected;
- **`connection`** — the evidence block the command hands back under `--json` at the
  **top level, as `connection`**: `{process, pbiType, stateMapNeeded, authPath,
  fetchedAt, basis}`. `--json` prints the answer document itself and wraps it in no
  envelope, so there is no `data` to reach through — this file said otherwise once and
  it cost a live run a retry. Same shape as the two caches `parents` writes, and the
  panel's ADO card reads it.

Revalidate with `validate-manifest.py` after the write, as every mutating command does.

**A `CHANGE` row is offered and never taken silently.** Running `connect` against a manifest
somebody already configured re-probes and reports; the value already in the file may be the
one a person chose against this command's advice, so each difference is a question, not an
edit.

**Credential expiry is not recorded, and that is the answer rather than a gap.** Neither
transport can be asked for it — a PAT's expiry needs the token itself or an
organization-admin scope this connector never requests, and the Azure sign-in's access
token expires hourly and renews itself. What `connection` records instead is which auth
path was in effect *and when access was last proven*, which is what turns a 401 six weeks
from now into "that PAT expired" rather than "the configuration is broken". Say that;
do not invent a field.

### 6. Hand off

`/audit:sync status` to see the connector's own report of what is linked, and
**`/audit:sync parents`** next when this board is a tree — it caches the backlog levels and
the parent-shaped items, without which every parent link reports `not verified`.

## Subcommand: `push [bugs|tasks|all]` (default `bugs`)

Optional scope flags: `--task <id>` / `--phase <id>` narrow the plan to one task (or
one phase: its PBI + its tasks/bugs) — the cheap way to heal one item's drift after a
failed echo.

1. **Phase work items** (when `phaseWorkItems` is not `false` and scope includes
   tasks): resolve `types.pbi` — null/absent → auto-detect and WRITE THE PICK BACK
   into `meta.ado.types.pbi` (tracker-sync.md → "Process templates"); the write-back
   happens inside this confirm-gated, index-locked run. Every in-scope phase lacking
   `phase.ado` gets a CREATE in the plan.

   **Where that branch hangs — per item, resolved by one function.** A phase may
   declare its own `adoParent`; `meta.ado.parentWorkItem` is the manifest-wide
   FALLBACK, still read and still the right answer for "all of this audit hangs
   under Feature X". Do NOT re-derive the precedence here — run the door, which is
   the same code the validator and the panel ask:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-ado-parent.py" \
     <manifest> [--all | --phase <id> | --task <id>] [--json]
   ```

   Exit 0 = every in-scope item has a place (**including "no parent anywhere"** —
   uncategorised work is an answer and a create, not an error). **Exit 1 = a
   hierarchy violation: do NOT create those parent links**, carry the findings into
   the plan below. Exit 2 = unreadable input or a scope naming nothing — stop, and
   never read it as a pass.

   The rules it applies, so the plan can be read: a task under `phaseWorkItems`
   hangs under its phase's work item and its own `adoParent` is INERT (warned, not
   ignored); an item's own `adoParent` beats the fallback; an explicit `null` means
   it hangs under nothing *even when the fallback is set*; absent falls through to
   `meta.ado.parentWorkItem`; neither is a free-standing branch nobody planning from
   that board will see.
2. Build the plan: for each in-scope item —
   - `item.ado` **null/absent** → CREATE (`az boards work-item create --type <type>
     --title ... --fields ... --output json`);
   - `item.ado.id` set → **diff the mapped fields**, and only when something differs
     → UPDATE (`az boards work-item update`). No-op items are skipped.

   **Fetch the linked side for that diff with the same door `status` step 3 uses** —
   `fetch-ado-items.py <manifest> --out fetched.json`, one query per chunk, bounded.
   Not one `az boards work-item show` per item: a push over a whole manifest reads
   exactly as many items as `status` does, so a per-item loop here would be the same
   defect one subcommand over. **Exit 1 means the payload is partial, and a push must
   not diff from it** — an item whose current state was never read would be diffed
   against nothing and updated blind. `work-item show` keeps its place further down
   for what it is actually for: reading ONE item back after writing it
   (tracker-sync.md → parent read-back).

   The batch already returns `System.ChangedBy` and `System.ChangedDate`; keep them,
   they are what step 2c reads, and a fetch that dropped them would leave 2c unable to
   tell your own write from somebody else's.
2c. **Whose card is this, and who moved it last — every UPDATE, before the confirm.**
   Take the payload `fetch-ado-items.py --out` already wrote (each `{id, fields}`)
   and stamp `mapped` onto it with the translation door — the fetch deliberately
   does not invent that field, and this file no longer carries a table anyone could
   apply by hand:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/read-ado-links.py" \
     <manifest> --items fetched.json --out mapped.json
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/explain-ado-drift.py" \
     <manifest> --items mapped.json
   ```

   **The first command is not optional and its exit 1 is a stop here**, harder than
   in `status`: an unstamped payload makes the count in step 3 (`K update(s) would
   overwrite a change made after our last sync`) structurally zero, and that count is
   what the confirm gate is asking the operator to read. A push confirmed against a
   zero nothing could have reached is the failure this pair exists to prevent.

   Exit 0 = answered; **exit 2 = could not read the input, so stop rather than
   push blind**. There is no exit 1: "somebody else moved this card" is the normal
   state of a board several teams write to, and refusing over it would make this
   command useless where it matters most. Do not reimplement the comparison here —
   `_ado_drift` owns it, and a second copy in prose is a second answer.
2b. **Conformance gate — every CREATE, before the confirm.** `meta.ado.conventions`
   says what an item must look like to BELONG on this board (skeleton, mandatory
   markers, tag vocabulary, parent). For each CREATE, write the payload you are about
   to send and run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/check-ado-item.py" \
     <manifest> --item <payload.json>
   ```

   Exit 0 = create it. **Exit 1 = do NOT create it**; carry its findings into the plan
   printed below so the operator sees the refusal before deciding anything, not after
   the item is on the board. Exit 2 is unreadable input — stop, do not treat it as a
   pass. A board with no `conventions` block exits 0 and says nothing was checked;
   that is an answer ("this board has no standard"), not a silent success.

   **The command MERGES `meta.ado.fields` into the payload before it grades it, so
   send back what it hands you** — the fields it printed (`MERGED: …`), or `payload`
   under `--json`. Sending the payload you wrote instead creates an item without the
   fields the gate just counted as present, which is how a green gate still lands a
   non-conforming item. A malformed `meta.ado.fields` is exit 2, not 1: the config
   could not be applied, which is not the item's fault.

   **A `NOTE:` line is not a refusal, and exit 0 can now carry one.** `requireParent`
   is scoped to the item kinds this connector actually parents, so on a board that asks
   for a parent on every card a bug create is exempt — and the gate PRINTS which rule it
   did not apply and to which item rather than narrowing in silence (`parentRuleExemption`
   under `--json`). It moves neither the exit code nor `conforms`. Carry it into the plan
   below **beside the create it describes**: a board's standard that quietly stopped
   applying is exactly the silent pass the printing exists to prevent, and the operator
   confirming the push is the person entitled to know.

   **Do not reimplement the rule here.** It is Python with cases precisely because
   prose cannot be tested — a second copy in this file is a second answer, and the
   first time they disagree the board is what tells you.

3. Print the plan (`N creates [of which K PBIs], M updates, J in sync`, plus the
   `types.pbi` auto-detect pick when it happened, plus `R refused by
   meta.ado.conventions` with each item's findings when the gate refused any) and
   **confirm via AskUserQuestion before the first write** — ADO writes are
   outward-facing and visible to the whole team. A refused item is never offered for
   creation; fix the manifest (or the conventions) and re-run.

   Carry step 2c's answer into that plan, because it is the part the confirm gate
   exists for:
   - the count line, **printed even when it is zero** — `K update(s) would
     overwrite a change made after our last sync` — with the ids, the writer's name
     and the moment for each. A number that appears only on bad news cannot be told
     apart from a number nobody computed;
   - per UPDATE row, whose card it is: `created here` / `imported from ADO` /
     `origin unknown (link written before the field existed)`.

   **This changes nothing about what the command may do.** No extra question, no
   refusal, no new switch: several writers on one board is normal, and this plugin
   does not arbitrate who owns a card. It just stops describing somebody else's
   card as if it were ours, and stops reporting a difference as if only two
   readings existed.

3b. **The parent block, printed verbatim from the door.** `resolve-ado-parent.py`
   emits one line per item — `<kind> <id> -> #<parent> -- <basis>` — plus a head
   line carrying BOTH counts, `R refused by the hierarchy check` and `U
   uncategorised (no parent anywhere)`, **and both are printed even at zero**: a
   number that appears only on bad news cannot be told apart from a number nobody
   computed, and the confirm gate is where the operator has no other way to learn
   the check ran. Below them come the links the type check could not verify, with
   the reason (`meta.ado.hierarchy` not cached → run `/audit:sync parents`), and the
   equal-rank NOTES, which are never refusals.

   Do not re-render those lines — paste what the door printed. A second rendering
   is a second answer, and the first thing to disagree would be a count.

   A refused item is never offered for creation, exactly like a
   `meta.ado.conventions` refusal: fix the declaration (or the board) and re-run.
4. **Assignment proposal** (only when `meta.ado.identityMap` has entries): for each
   CREATE in the plan, resolve the item's phase — a task's own phase; a bug reaches a
   phase only through its materialized `taskId` (an unmaterialized bug has no phase and
   draws no proposal). Resolve that phase's area **owner** the way every other surface
   does (`meta.areas`, written order; explicit `owner: null` is an answer — "nobody owns
   this" — and stops the lookup). An owner WITH an identityMap entry gives the item a
   proposed assignee. Then ask ONE AskUserQuestion, **batched by proposed assignee**
   (multi-select; one option per assignee: `<mapped ADO identity> — owner of area <tag>
   — N item(s)`; more than 4 distinct assignees → chunk into further questions):
   accepted groups get `--assigned-to <mapped>` on their creates, declined groups are
   created unassigned as today. Batched because a push routinely carries many same-area
   items and the decision is per-person, not per-item — asking the same question N times
   trains the user to stop reading it. **Never assign silently**: no accepted answer, no
   `--assigned-to`. When an owner exists but has NO identityMap entry, say so in one
   line — `owner <ledger id> (area <tag>) has no identityMap entry — no assignment
   proposed` — so the missing mapping is visible instead of silently skipped. UPDATEs
   never get an assignment proposal: the ADO-side assignee may have been set by a human
   in ADO since the create, and this command must not fight that — assignment is
   proposed at an item's birth only.
5. Execute item by item, phases first. After each successful create, IMMEDIATELY Edit
   the manifest: `item.ado = {id, url, lastSyncedAt: <ISO now>, origin: "created"}`
   (then revalidate).
   After each update, bump `lastSyncedAt` — and **never touch `origin` on an
   update**: where a card came from does not change, and rewriting it on the first
   push after an import would erase the only record that it was somebody else's.
   A link that carries no `origin` (written before the field existed) stays without
   one rather than being backfilled with a guess. On any failure: report it, keep
   what succeeded, stop — a re-run continues where it left off. Per item:
   - **State** per `stateMap` (defaults above; `null` = skip State), applied as a
     SECOND call after the create (only the initial state is settable at creation);
     a rejected state degrades per tracker-sync.md and never aborts the batch.
   - **Sprint stamp** per "Sprint resolution" above.
   - **Remaining Work**: a task moving to its done-state with `onComplete` configured
     attempts `remainingWork` (default 0; explicit `null` = never) in the SAME update
     as the state; a field-rule refusal (stock processes force-clear it at done) →
     retry state-only, report the skip.
   - **Tags**: read the item's current tags, merge in the provenance tag
     (`meta.ado.tag`; absent = `audit-plugin`, null = none), write the union —
     never write the tag list blind.
   - **Parent links**: the resolved parent from step 1 for each phase (and, with
     `phaseWorkItems` false, each task); with `phaseWorkItems` on, each of a phase's
     children is linked to the phase PBI after it exists. **The argument contract
     and the read-back are in tracker-sync.md → "Parent links"** and are not
     restated here, because a second spelling of that call is where a swap hides.
     Three things are non-negotiable at this step:
     - **the item being UPDATED is the CHILD** — both transports agree, and the
       table there shows them side by side;
     - **read `System.Parent` back off the child and assert it equals the intended
       parent.** A swapped call SUCCEEDS — both ids are legal work items and the
       response says nothing about direction — so the read-back is the only thing
       that catches it. It is one field on an item this step already touched;
     - **a mismatch, or a link the server rejects, degrades PER ITEM**: report it
       with both ids, keep the item and everything that succeeded, and continue —
       the same shape as the invalid-state fallback. Never abort the batch over a
       parent link.
     Read existing relations first and skip when the link is already there.
     **A parent is applied at CREATE only.** A changed `adoParent` on an
     already-linked item is reported by `status` as parent drift and never silently
     re-parented: the board side may have been moved by a person, and re-parenting
     behind their back is the same override this feature exists to undo.
   - **Comments** (opt-in via `meta.ado.comments`): `onBlocked` → on a task entering
     its blocked-state, comment with attempts, last `outcome.technical` and blockers;
     `onComplete` → on the done move, comment with the sign-off note and the task's
     `commit` SHA. Generated comments name their actor (`audit-plugin`).
6. When pushing a `fixed` bug with `fixedIn`, add a work-item comment
   (`az boards work-item update --id <id> --discussion "Fixed in <sha>"`) — this
   legacy comment is unconditional, independent of `meta.ado.comments`.
7. Report: table of `manifest id | ado id | action taken` (assigned-to and sprint
   stamp noted where applied).

## Subcommand: `pull [bugs|sprint]` (default `bugs`)

**Dedup rule (both flavors)**: a candidate whose id appears in ANY manifest `ado.id`
— live tasks, bugs, phases, AND parked `proposals[].payload` items — is dropped. A
re-pull imports nothing. Never modify ADO during `pull`.

### `pull bugs`

1. Query candidate bugs, **selecting the parent in the SAME query** — WIQL can
   `SELECT [System.Parent]`, so capturing where a card already hangs costs nothing
   and adds no per-item call:
   `az boards query --wiql "SELECT [System.Id], [System.Parent] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] = '<types.bug>' AND [System.State] <> 'Closed'"`
   (add an AreaPath clause when `meta.ado.areaPath` is set).
2. Drop already-linked items (dedup rule above).
3. For each remaining item, show `id | title | state | assignee` and ask
   (AskUserQuestion, multi-select) which to import.
4. Import each selected item as a manifest bug following `/audit:bug add`'s shape and the
   conventions doc: next `BUG-<n>`, `status: "open"`, title/description from the work
   item, `repro` from its repro steps,
   `ado: {id, url, lastSyncedAt, origin: "imported"}` — the card was made by
   somebody else and a later push has to be able to say so.
   **When the card has a board parent, write `adoParent: {id, type, title, url,
   source: "imported", observedAt: <ISO now>}`** — a SIBLING of `ado`, never a field
   inside it, because `ado` is the link sync writes and `adoParent` is a declaration
   about where the work belongs. **A card with NO parent gets no `adoParent` key at
   all — not `null`.** Absent means "fall through to `meta.ado.parentWorkItem`";
   `null` means "hangs under nothing", and a pull is not entitled to make that
   declaration on the operator's behalf. `type` and `title` come from the same
   fetch; they are the BASIS the hierarchy check reads, and without them every link
   reports `not verified`. `reportedBy`
   comes from the work item's assignee (creator when unassigned) via **reverse lookup**
   in `meta.ado.identityMap`: when some entry's VALUE matches that ADO identity
   (case-insensitively), write the LEDGER identity — the key — so the imported bug's
   `reportedBy` speaks the same form the usage ledger's author column and
   `meta.areas[*].owner` do, and the author/owner filters in status/report/panel line
   up. Two keys sharing one value (the validator warns about that map) → the FIRST in
   map order wins; name the pick in the report. No matching entry → today's
   `reportedBy: "ado:<assignee-or-creator>"`, unchanged. The lookup applies ONLY to the
   bug being imported right now: **existing manifest rows are never rewritten** — not by
   `pull`, not by a later identityMap edit. `reportedBy` is a record of what was known
   at import time, not a live view. Revalidate.
5. Report + handoff: `/audit:bug fix BUG-<n>` to materialize a fix task.

### `pull sprint`

Imports the current sprint's PBIs and tasks as **parked proposals** — nothing enters
the live plan without `/audit:propose materialize`.

1. Resolve the iteration: `meta.ado.sprint` set → current-iteration resolution;
   else `meta.ado.iterationPath` set → use it; else STOP — a sprint pull needs an
   iteration to pull from.
2. **Scope the query** — one sprint can span multiple repos, and the filters say
   which items belong to THIS manifest: `meta.ado.pull.areaPath` (falls back to
   `meta.ado.areaPath`) → `[System.AreaPath] UNDER '<path>'`; each `meta.ado.pull.tags`
   entry → `[System.Tags] CONTAINS '<tag>'`. Filters AND-compose. **No filter
   configured → refuse to import blind**: list the sprint's items read-only, require
   explicit selection (picked items or entered ids), and OFFER to persist the chosen
   filter into `meta.ado.pull` (a manifest edit, under the lock, revalidated).
3. Query `<types.pbi>` items in the iteration (WIQL on `[System.IterationPath]`),
   plus their child tasks (relations); apply the dedup rule.
4. Show candidates grouped by PBI (`id | title | state | children`) and ask
   (AskUserQuestion, multi-select) which PBIs to import.
5. Import each selected PBI as ONE parked proposal (conventions doc → Proposals):
   next `PROP-<n>`, `origin: "ado:sprint <iterationPath>"`, `payload.phase` = a
   synthesized phase with the next reserved `P<n>` id, title from the PBI,
   `ado: {id, url, lastSyncedAt, iterationPath, origin: "imported"}` on the phase
   (the proposal's own `origin` above says which SPRINT it came from; `ado.origin`
   says who made the CARD, and both are needed once a push starts writing to it),
   plus `adoParent` on the phase when the PBI has a board parent — same rule and
   same reason as `pull bugs` above: `SELECT [System.Parent]` in the same query, no
   key at all when there is none,
   child tasks from the PBI's child work items (each carrying its own `ado` link
   with `origin: "imported"`, `files: []`), and a
   description noting `imported from ADO — scope files/tests before running`,
   which names a real verb: `/audit:task scope <taskId> --files a,b`. It did not
   always — for a release that instruction had no executor, and an imported phase
   ran with `fileIndex` empty and the plan gate therefore inert. Orphan
   sprint tasks (no selected parent) group under one final proposal. Revalidate.

   **The synthesized phase's `testGate` comes from the manifest or is EMPTY. Never
   a guess.** ADO says nothing about how this repo proves work done, so the only
   honest sources are `meta.buildCommands` and nothing —
   `audit-task.py:_phase_gate` is the rule and it returns the basis with the
   value, including `meta.buildCommands is empty` and `the manifest declares no
   meta.buildCommands`. Print that basis. An EMPTY gate is a designed state, not a
   hole: sign-off then rests on review alone, and the phase says so.

   This is not a style note. An imported phase was given `testGate: ["lint"]`
   because a build key existed; `lint` on that repo runs a Python pre-commit suite
   and the phase's tasks touched only JSON and Markdown, so the phase could not
   pass its own sign-off — and correcting it meant a hand edit the plugin forbids,
   a `buildCommands` value that is a shell hack, or installing a third-party tool
   to satisfy a gate the plugin itself picked. A guessed gate is worse than no
   gate, because no gate says so. `/audit:phase retarget <phaseId> --gate-clear`
   is the way back if one is ever guessed again.
6. Report + handoff: `/audit:propose list` → `materialize`.

## Subcommand: `parents`

**Read-only against ADO.** It writes exactly two keys of the manifest —
`meta.ado.hierarchy` and `meta.ado.parentCandidates` — under the concurrency lock,
and revalidates after. It creates nothing, updates no work item, and changes no
`adoParent`: a declaration about where work belongs is the operator's, and a fetch
is not entitled to make one.

Both keys are **cached evidence**, so both carry a `fetchedAt` and a one-sentence
`basis` naming the query. Evidence with no moment cannot be aged, and evidence with
no basis has to be trusted rather than checked.

1. **The ladder** — which work item type may parent which, asked of THIS project.
   Fetch the payload, then hand it to the door; **do not build the block by reading
   it**:

   ```bash
   az devops invoke --area work --resource backlogconfiguration \
     --route-parameters project=<project> --api-version 7.1 > backlogconfig.json

   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-ado-parent.py" \
     <manifest> --hierarchy-from backlogconfig.json
   ```

   What it prints **is** `meta.ado.hierarchy` — the ranks off `taskBacklog`,
   `requirementBacklog` and each `portfolioBacklogs[]`, the `fetchedAt`, and the
   `basis` naming the query — so write it in verbatim under the lock and revalidate.
   `--hierarchy-from -` reads the payload on stdin instead, for a piped fetch.
   Exit 0 = a ladder. **Exit 2 = the payload could not be read, or ranks no backlog
   level at all**: write nothing and say which, because an empty ladder cached as
   evidence reads as a project that ranks nothing and turns the type check off.

   **Do not re-derive where a bug goes.** Its rank comes from the payload's
   `bugsBehavior`, which is the only field that says (the type lists do not name a
   bug at all) — but the NAME that rank is filed under is `meta.ado.types.bug`, so
   a board that renamed the type gets its own name and prose naming the type instead
   files the rank under a name no work item carries. That is the same reason the
   chunk size and the state map are doors rather than paragraphs. tracker-sync.md
   → "Backlog levels" carries what the payload holds. **No table ships with the
   plugin**: the same organization runs one project at `asRequirements` and another
   at `asTasks`, so a shipped ladder would be wrong on the second board and
   confidently so.

2. **The candidates** — the parent-shaped items on this board right now, so a picker
   can offer them instead of asking for an id from memory. WIQL over the types that
   rank ABOVE the audit's own (from step 1), scoped by `meta.ado.pull.areaPath` or
   `meta.ado.areaPath` when either is set:

   ```
   SELECT [System.Id], [System.WorkItemType], [System.Title], [System.State], [System.AreaPath]
   FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] IN (...)
   ```

   Write `meta.ado.parentCandidates = {items: [{id, type, title, state, areaPath,
   url}], fetchedAt, basis}`. **Never an authority**: nothing resolves, validates or
   refuses against this list, and an item missing from it is not a wrong parent —
   only one created since the fetch. Say how the list was scoped in `basis`, so an
   empty list can be told from an unfiltered one.

3. Report what was written, then run the resolver over the whole plan so the
   operator sees what the new ladder changes:
   `resolve-ado-parent.py <manifest> --all`. A link that read `not verified` before
   this run may now be a NOTE or a refusal, and that is the point of having fetched.

## Subcommand: `status`

Read-only, no ADO writes, no manifest writes.
1. Lead with the connector line: `enabled`/`echo`/`phaseWorkItems` state (and the
   DISABLED banner from Preflight 3 when off), `sprint: <resolved path>` or
   `sprint: unresolvable (team '<t>')` when resolution fails.
2. **The link inventory is a door, not a walk you write here.** Counting linked vs
   unlinked means reading every phase, every task and every bug — which on the
   sharded layout is a walk over the ASSEMBLED manifest and not over the file at
   `manifestPath` (Preflight 1). Do not do it by hand:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/read-ado-links.py" <manifest>
   ```

   Print its counts as it prints them — per kind, then the totals, then the target
   state each linked item's status means and which of `meta.ado.stateMap` or the
   built-in defaults answered. It also names the work items **more than one manifest
   item claims** (`SHARED: #<id> …`), with that count printed even at zero: nothing
   validates that a work-item id is claimed once, so this is the only place it is
   ever counted, and two rows carrying one id read as a typo until it is said.

   Exit 0 = answered. **Exit 2 = the manifest or one of its shards could not be
   read** — stop and say which file, because a short table is indistinguishable from
   a small board. Do not re-tally any of it below; the numbers in step 3's table are
   this command's.
3. For linked items, fetch the ADO side **in one query per chunk — never one call per
   item** — and print:
   `manifest id | title | manifest status | ado id | ado state | drift?` — drift = the
   `stateMap`-mapped state differs from the ADO state. Add sprint drift where stamped:
   `ado.iterationPath` ≠ the currently-resolved iteration → `sprint drift (push restamps)`.

   **`az boards work-item show` is not the command for this and never was.** It takes
   a single `--id` and refuses a comma list, so the instruction that named it while
   asking for a batch could not be obeyed: the run looped, and every linked item paid
   a fresh CLI start-up (tracker-sync.md → live-gate F5). **Do not re-derive the batch
   here** — the chunk size, the field list and the per-call bound are the three things
   prose cannot be held to, which is exactly why they are code now:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/fetch-ado-items.py" \
     <manifest> --out fetched.json [--chunk <n>] [--timeout <seconds>]
   ```

   Exit 0 = every chunk answered and `fetched.json` is complete for the ids asked
   for. **Exit 1 = at least one chunk did not answer, so the payload is PARTIAL** —
   it names the ids it has no news about, and you stop rather than build a table from
   it, because an absent row is not an unchanged one. Exit 2 = the manifest or
   `meta.ado` could not be read. `--dry-run` prints the queries and the call count
   without spending a call.

   It reports the shape of what it did rather than implying one call —
   `N id(s) in M quer(y|ies) (chunk limit L, bound Bs per query)`, then
   `fetched N of M linked item(s)` — and prints those **even at zero**, because a
   count that appears only on success cannot be told from a count nobody computed. An
   id it asked for that no row came back for is named (`NO ROW: #<id>`): a work item
   deleted or moved out of the project is a thing to say, not a row to drop from a
   table that then looks complete.

   **The chunk size is a limit and is stated as one.** The service's real ceiling is
   on the WIQL TEXT (`VS403309`, quoted with its probe in tracker-sync.md →
   live-gate F5), so the default id count is an operating point far below it — a
   chunk sized at the ceiling would start refusing the day an id grew a digit. Print
   the field list, the chunk limit and the bound rather than restating them here:
   `fetch-ado-items.py <manifest> --dry-run`.

   **When the session carries the MCP tools** you may run the same WIQL through
   `mcp__azure-devops__wit_query` instead — one call, no subprocess. It is the
   transport this repo has NOT been able to probe (the MCP server authenticates as a
   different identity than the lab board grants), so take the `SELECT` list from
   `--dry-run` above, and give the tool call the same bound and the same named
   outcome. Where the two could disagree, the `az` shapes are the measured ones.

   **Stamp the payload before you compare it — the drift door cannot invent the
   manifest's side.** `explain-ado-drift.py` reads `mapped` off each entry and
   reports `state not compared (no mapped state supplied)` for every row that has
   none, which is honest per row and useless over a board: `summarize()` counts an
   overwrite only where the two states DIFFER, so an unstamped payload closes with
   `0 would overwrite a change made after our last sync` — the one number the push
   confirm gate exists for — on a board where the answer was never computed. Run the
   translation door over the file the fetch just wrote:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/read-ado-links.py" \
     <manifest> --items fetched.json --out mapped.json
   ```

   Then hand **`mapped.json`**, never `fetched.json`, to the door below. Exit 0 =
   stamped, with each entry it could not stamp named and why. **Exit 1 = entries
   were given and not one could be given a state**, so every reading below has no
   basis — report that and stop rather than printing a table of `state not
   compared`. Exit 2 is unreadable input. The translation itself is not restated
   here: see *The state translation is a door* above.

   **A difference has THREE readings, not two**, and the third is the common one on
   a board several teams write to: somebody else moved this card after we last
   touched it, and neither side is wrong. Do not decide that here — run the same
   door push step 2c runs (`explain-ado-drift.py <manifest> --items mapped.json`,
   `--json` when you want to compose the table yourself) and print what it answers
   in the `drift?` cell:
   - `local ahead — push is the fix` (nobody wrote after our `lastSyncedAt`);
   - `external (<who>, <when>) — push would overwrite it`, naming the writer from
     `System.ChangedBy` so the reader can go and ask that person;
   - `unknown — never synced or unstamped`, which draws **no** suggested action:
     the basis for one is missing, and saying so is the answer.

   Append each row's card provenance from `ado.origin` — `created here` /
   `imported from ADO` / `origin unknown` — because "we made this card" and "we
   adopted somebody's card" are different things to be about to write to.
3b. **Parent drift** — one more cell on the same row, `parent?`. A parent is
   applied at CREATE only, so a linked item whose `adoParent` no longer matches the
   board is a difference to REPORT and never one to fix silently: the card may have
   been moved by a person, and re-parenting behind them is the same override this
   feature exists to undo. From the `System.Parent` you already fetched in step 3 —
   it is in that `SELECT` list, and it needs no `--expand relations` on either the
   query or a plain `show` — against the resolved parent from
   `resolve-ado-parent.py --json`. **An item with no board parent comes back with the
   key ABSENT, never `null`** (measured, live-gate F5), and that is the distinction
   the cells below rest on: *the board hangs it nowhere* and *we did not ask* must not
   collapse into one row.
   - `parent ok` — they agree;
   - `parent drift: manifest #<a>, board #<b> — applied at create only, so push
     will NOT re-parent` — say both ids and say that push leaves it alone, or the
     reader will wait for a fix that is not coming;
   - `parent: none declared, board #<b>` — the board hangs it somewhere this
     manifest does not describe, which is information and not a defect;
   - `parent: #<a> declared, board none` — declared but never applied, usually an
     item linked before the declaration was written.

   Close with the counts, **printed even at zero**: `parents: N ok, M drifted, K
   uncategorised`. Suggest nothing per row here — `status` is read-only, and the
   remedy for real drift is a human decision about somebody's board.

4. **Identity mapping** (only when `meta.ado.identityMap` has entries): per item, append
   one compact `owner` column to the table above, resolving the item's phase-area owner
   exactly as push step 4 does — `<ledger id> → <mapped ADO identity>` when mapped,
   `<ledger id> (unmapped)` when an owner exists without an entry, `—` when no owner
   resolves. Close with one summary line: `identityMap: N owner(s) mapped, M unmapped`
   (distinct owners across the areas in play). Display only — `status` stays read-only
   and proposes nothing here; an unmapped owner is push's business.
5. **Conformance of what is already there** (only when `meta.ado.conventions` is set).
   Run the gate over the ADO side itself — the same `fetched.json` step 3 wrote, not a payload you assemble:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/check-ado-item.py" \
     <manifest> --fetched <fetched.json>
   ```

   **`--fetched`, never `--item`.** They are different shapes and different verdicts: a fetched row spells the work item type and the parent INSIDE `fields`, so grading it as a create payload refused items whose parent was set while the type-scoped rules checked nothing at all. `--item` refuses that shape outright now, and this flag translates it. Do not translate it in prose here — `_ado_conventions.as_gradable_item` owns which key holds what, and a second copy is a second answer.

   Append the command's per-row answer to each row's `conforms?` cell and print its closing line as it comes: `conventions: N of M linked item(s) conform` is computed there, so do not re-tally it. A row printed as `NOT GRADED` is neither conforming nor refused — the payload carried no work item type for it, so say that and leave the cell unfilled rather than guessing.

   Exit 0 = every graded row conforms. **Exit 1 = at least one item ALREADY on the board does not conform** — a finding to print, not an error to stop on, and not a refusal to create anything. Exit 2 = something was not graded at all (unreadable payload, a row with no work item type, or the `--json` payload handed over instead of `--out`, which can be partial) — report it as a missing basis, never as a clean board. `meta.ado.fields` is NOT merged on this path: that template is what a CREATE must send, and merging it here would grade fields the board does not have.

   This is the half that makes the push gate honest. The gate above lives in prose,
   and prose is the one surface here nothing can test — so *did the orchestrator
   actually run it* is unprovable at the point of writing. It is provable afterwards:
   a non-conforming item sitting on the board is evidence the check was skipped, and
   this line is where that shows up. Read-only as the rest of `status` is — it reports,
   it never fixes.

6. Suggest the next action (`push` / `pull`) **per drift class, not per
   difference** — that distinction is the whole point of step 3. `local ahead` →
   `push`. `external` → say what each choice costs (`push` overwrites their change,
   editing the manifest keeps it) and let the human pick; recommending `push` here
   would be recommending that somebody's work be overwritten sight unseen.
   `unknown` → suggest nothing and say why, then close with the origin split so a
   reader knows how much of this board is even ours.

## Non-goals (say no when asked)

- **No credential handling in `connect`, ever** — no prompting for a token, no writing one
  anywhere, no echoing one, and no expiry DATE invented to fill a field neither transport
  can supply. `connect` verifies and records WHICH BOARD and which auth PATH; auth itself
  belongs to `az` / the MCP server.
- No `connect` write beyond the manifest, and none at all before its confirm: it creates no
  work item, updates none, and a rung that stops leaves `meta.ado` exactly as it was.
- No two-way merge in one run — one direction per invocation keeps conflicts human-visible.
- No deletion of ADO work items, ever. Closing happens via state mapping.
- No syncing of `deferred` — and `proposals` sync only in the ONE direction `pull
  sprint` creates them; they become pushable work items after materialization.
- No board-column (`WEF_`) writes, ever — cards move via `System.State` only, and a
  column not backed by a state is reported as unreachable, not faked (tracker-sync.md).
- No creation from the orchestrator echo — the echo UPDATES linked items only;
  creation lives here, behind this command's confirm gate.
- No silent RE-parenting. A parent is applied at CREATE; a changed `adoParent` on a
  linked item is reported as drift by `status` and left alone, because the board side
  may have been moved by a person and this command does not fight that.
- No hierarchy table shipped with the plugin, and no guessing when the cache is
  absent: `parents` asks the project, and an unfetched ladder reports every link as
  `not verified` while the create proceeds. A missing basis is a thing to say.
- No silent assignment from `identityMap`, and no `task.assignee` field — the map lives
  in `meta.ado`, push asks before every `--assigned-to`, and pull labels new imports
  without ever rewriting existing rows.
