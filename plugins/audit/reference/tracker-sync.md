# Tracker sync conventions

Shared contract for mirroring the audit manifest into an external work tracker —
read by `/audit:sync` and by the orchestrator's tracker echo (see `orchestrator.md`).
The first half is deliberately **tracker-neutral**: one binding exists today (Azure
DevOps, `meta.ado`), and a future binding (e.g. JIRA as `meta.jira`) mirrors these
shapes and key names 1:1 instead of inventing parallel vocabulary. The second half is
the ADO binding — the only place ADO-specific mechanics belong.

## The contract (tracker-neutral)

### The link object

The manifest side of every link is the item's per-tracker field — `ado` today —
holding `{id, url, lastSyncedAt}` plus an optional `iterationPath` stamp (sprint
mode) and an `origin` — `created` when the push made the item, `imported` when a
pull adopted one somebody else made. `origin` is written once, at the link's birth,
and never rewritten: where a card came from does not change. Absent means
unrecorded (a link older than the field, or hand-written) and every surface **says
so** rather than assuming `created` — claiming this tool made somebody else's card
is the one wrong answer available here. The provenance tag cannot stand in for it:
`tag` is merged onto every item a push TOUCHES, so it proves contact, not
authorship. The **id type is per-tracker**: ADO ids are integers; a JIRA binding would
carry string keys (`PROJ-123`) in its own `jira` field with its own `$def`. Links are
written ONLY by the sync command (and `lastSyncedAt` bumps by the echo) — never by
hand. Links are never deleted: disabling the connector freezes them.

### Config keys (mirrored shape per tracker)

| Key | Meaning (defaults in the binding half) |
|---|---|
| `enabled` | master switch; absent = on; `false` freezes everything, keeps links, `status` still reports |
| `echo` | absent = on; the orchestrator best-effort UPDATES linked items on task done/blocked/reopen and phase sign-off; never creates |
| `phaseWorkItems` | absent = on; one phase-level work item per phase, task/bug items parent-linked under it (the push plan lists the creates, so the confirm gate keeps it consented) |
| `types` | manifest kind → tracker work-item type name |
| `stateMap` | manifest status → tracker state name, per kind (`task`/`bug`/`phase` — phase-level items carry a DIFFERENT state vocabulary than tasks); a `null` value = never move that transition (the team moves that card by hand) |
| `tag` | provenance tag stamped on pushed/echoed items; absent = the binding's default (`audit-plugin`), custom value pairs with `pull` scoping for per-repo symmetry on shared sprints, `null` = no tag |
| `onComplete` | what the done-transition writes besides state (e.g. `remainingWork`) |
| `comments` | opt-in generated comments per event (`onBlocked`, `onComplete`); a generated comment always names its actor |
| `sprint` | dynamic iteration resolution (`{team, mode: "current"}`); absent = static path config |
| `pull` | import scoping filters (`areaPath`, `tags`) — which of a shared sprint's items belong to THIS repo |
| `identityMap` | ledger identity → tracker identity. The **ledger identity is always the key** — it is the identity the plugin owns (usage ledger author column, area owners); the tracker is the foreign side |

### The idempotency contract

Every binding honors all five, in this order of importance:

1. **Create-once**: the link is written into the manifest IMMEDIATELY after each
   successful create, so an interrupted run resumes without duplicating.
2. **Diff-before-update**: fetch the tracker side, compare the mapped fields, write
   only when something differs; in-sync items are skipped and reported as such.
3. **Confirm-before-first-write**: a push prints its plan (`N creates, M updates,
   K in sync`) and asks before the first outward-facing write.
4. **Lock + revalidate**: manifest writes hold the concurrency lock
   (manifest-conventions.md) and revalidate after every mutation.
5. **One direction per invocation** — no two-way merge in one run; conflicts stay
   human-visible.
6. **Classify before you overwrite.** A tracker item that differs from the manifest
   has three readings, not two: our side moved, their side moved, or there is no
   basis to say. The third party is the normal case on a board with several teams,
   so a push says — before its confirm — how many updates would overwrite a change
   made after the link's own `lastSyncedAt`, and whose card each one is. This needs
   no identity of ours: a push writes the tracker first and `lastSyncedAt` second,
   so for our own write the tracker's change stamp is never the later of the two.
   A binding must therefore keep whatever the tracker's "last changed at / by"
   fields are called (ADO: `System.ChangedDate` / `System.ChangedBy`) when it
   fetches for the diff — they cost nothing extra and they are the basis for the
   only honest thing this step can say.

### The echo contract

The orchestration echo is the automatic half of the connector, and it is deliberately
weaker than sync:

- **Update-only.** It never creates work items — creation is consent-gated in the
  sync command, and an echoed update inherits that consent because the link it
  updates was created under the confirm gate.
- **Never asks, never blocks.** No AskUserQuestion, no retries, no aborting the run;
  a failed echo is one report line.
- **Self-healing.** Anything the echo missed (offline, disabled mid-run, rejected
  state) is exactly what `push` reconciles — tracker state is externally observable
  and diffable, so a missed echo is drift, not loss.
- **Minimal manifest footprint.** The echo's only manifest write is the item's
  `lastSyncedAt`, riding the same shard edit the status transition already makes —
  no extra lock cycle, no index write.

### Proposal-based pull

Imported sprint items land as **parked proposals**, never directly in the live plan —
review and materialize via `/audit:propose`. Scoping: one sprint can span multiple
repos, so `pull` filters (`areaPath`, `tags`, AND-composed) say which items belong
here; with **no filter configured the pull refuses to import blind** — it lists the
candidates, requires explicit selection, and offers to persist the chosen filter.
Regardless of filters, the candidate list is always confirmed before proposals are
written. Dedup scans EVERY link in the manifest: live tasks/bugs/phases AND parked
proposal payloads — a re-pull must import nothing.

### Journal

Link creation (id appearing on an item) is journaled as an `ado.link` row by the
manifest-diff hook — the hook stays the journal's only writer. `lastSyncedAt` bumps
deliberately draw **no** journal row (the plan did not move). Known limitation: bug
pushes are unjournaled (the journal collector walks phases only).

## Azure DevOps binding (`meta.ado`)

### Field reference names

| Concept | ADO field |
|---|---|
| Title | `System.Title` |
| State | `System.State` |
| Iteration | `System.IterationPath` |
| Area | `System.AreaPath` |
| Tags | `System.Tags` |
| Severity | `Microsoft.VSTS.Common.Severity` |
| Remaining Work | `Microsoft.VSTS.Scheduling.RemainingWork` |

### Board movement is `System.State` — never `WEF_` fields

A card's board column physically lives in per-team hidden fields
(`WEF_<board-guid>_Kanban.Column` / `.Done`): the GUID differs per team board, one
work item carries one `WEF_` set per board that shows it, and writing them is
unsupported plumbing. Setting `System.State` moves the card via the team's
column↔state mapping — supported and team-agnostic. Two honest limits, to be said
rather than papered over: **split columns** (Doing/Done sub-columns) and a **column
not backed by a state** (e.g. a "Review" column mapped to no state of its own)
cannot be targeted; if the user's `stateMap` aims at one, the connector reports the
rejection instead of faking the move.

### Process templates: states and the PBI type

| Process | Phase-level type | Task states | Bug resolution |
|---|---|---|---|
| Scrum | Product Backlog Item | To Do / In Progress / Done | New / Approved / Committed / Done |
| Agile | User Story | New / Active / Closed | New / Active / Resolved / Closed |
| CMMI | Requirement | Proposed / Active / Resolved / Closed | same family |
| Basic | Issue | To Do / Doing / Done | To Do / Doing / Done |

The built-in `stateMap` defaults (`done`→`Closed`, `fixed`→`Resolved`, …) name
**Agile-process states**. On Scrum, `Closed` does not exist on a Task — Scrum
projects set `meta.ado.stateMap` (e.g. `done`→`Done`), and `/audit:doctor` carries
the advisory.

`types.pbi` auto-detect (when `phaseWorkItems` is true and `types.pbi` is
null/absent): list the project's work item types with the read-only call
`az devops invoke --area wit --resource workitemtypes --route-parameters
project=<project> --api-version 6.0`, pick the first of **Product Backlog Item →
User Story → Requirement → Issue** that exists, report the pick in the push plan,
and write it back into `meta.ado.types.pbi` inside the same confirm-gated run — so
the choice is deterministic afterwards and visible in the file.

### Parent links (phase → children)

Relation type `System.LinkTypes.Hierarchy-Reverse` (child → parent). CLI:
`az boards work-item relation add --id <childId> --relation-type parent
--target-id <pbiId>`; MCP fast path: `wit_work_item_link_write`. Idempotency: read
the child's existing relations first (`az boards work-item relation show --id
<childId>`) and skip when the parent link already exists.

### Current-iteration resolution (`sprint.mode: "current"`)

`az boards iteration team list --team "<team>" --timeframe current -o json` →
`[0].path` (form `Project\Sprint N`) plus `attributes.startDate/finishDate`; the MCP
`work` tool reads the same. An empty list means the team has no current dated
iteration → fall back to the static `iterationPath` (or no stamp) with ONE warning
and continue — the sprint stamp is decoration on a push, not its point. For pull
queries, WIQL offers `[System.IterationPath] = @CurrentIteration('[<project>]\<team>')`.

### States are applied by UPDATE, never at create (live-gate F2)

ADO's transition rule allows only the type's INITIAL state at creation —
`transitions[""]` lists exactly one state (proven live: even a valid `Done` is
refused on create). The create/state shape is therefore unconditional, not a
fallback: **CREATE without `System.State`, then UPDATE the mapped state.** A
target already equal to the initial state needs no second call.

### Invalid-state fallback

An `az boards work-item update` with a `--state` the type's process does not define
fails the WHOLE call. Recovery, per item: retry the same update **without**
`--state`, report `state '<X>' rejected — list this type's states and set
meta.ado.stateMap`, and continue with the next item. Never abort the batch over a
state name. Remember the vocabularies differ per kind: a Scrum PBI knows
New/Approved/Committed/Done and no "In Progress" — that is what `stateMap.phase`
exists for (live-gate F1).

### Remaining Work (live-gate F3)

`onComplete.remainingWork` is attempted in the SAME update call as the done-state
move (`az boards work-item update --id <id> --state "<mapped>" --fields
"Microsoft.VSTS.Scheduling.RemainingWork=<n>"`), and only on **task-category**
types — PBIs/stories do not carry the field in most processes. **Both stock
processes refuse it**: Scrum (Done) and Agile (Closed) carry a rule that force-
CLEARS Remaining Work in the done state (`TF401320 InvalidNotEmpty`), and the
whole call fails — state unmoved. Recovery, per item: retry the update with the
state alone and report the field skip. Note the goal is met anyway: a stock
process reaching its done state empties Remaining Work by itself; the config key
matters only for custom processes without the clear rule.

### Tags are read-merge-write, never wholesale (live-gate F4)

`System.Tags` updates REPLACE the item's whole tag list. Every tag write
therefore reads the item's current tags first, merges (provenance tag from
`meta.ado.tag`, default `audit-plugin`, null = none; plus the fixed `blocked`
marker where the transition calls for it) and writes the union back. Writing a
tag blind would erase the team's own tags — the polygon never noticed because the
connector owned every tag there.
