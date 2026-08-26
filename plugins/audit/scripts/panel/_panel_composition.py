#!/usr/bin/env python3
"""
What the plan SAYS: the phase/task composition rows, the bug rows, the ADO
honesty banner and the areas registry -- everything `/api/state` and
`/api/areas` render out of the manifest itself.

Split out of `_panel_state.py` (U3.1). Layer 4, above `_panel_paths` (3).

Stdlib only, Python 3.8 compatible.
"""
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _branch                # noqa: E402  (the naming convention, one expansion path)
import _priority              # noqa: E402  (what a valid tier is, and who holds tier 1)
import _ado_parent            # noqa: E402  (where ONE item hangs, and the marker for 'no declaration')
import _ado_tracked           # noqa: E402  (whether ONE item belongs on the board at all - three-valued)
import _ado_drift as _drift   # noqa: E402  (link_inventory: the ONE walk over ado links, at layer 2)
import _evidence_io as _ev    # noqa: E402  (the pointer's key and the ONE ledger read, at layer 2)
import _panel_paths as _paths  # noqa: E402  (the shared base, at layer 3)

# Carried by module-level alias so every body below reads exactly as it did in
# `_panel_state`, where these were siblings rather than imports.
_within = _paths._within
_config_path = _paths._config_path
_manifest_path = _paths._manifest_path
read_config = _paths.read_config


# --- the plan as the panel shows it ---------------------------------------------
# A phase's `area` -> its tags. One implementation, in `_areas`, shared with
# audit-status: this file and that one each had their own copy of the same six
# lines, and the day one of them learned something (trimming, de-duplication, the
# registry lookup) the panel and the terminal would have disagreed about which
# phases are in an area.
_areas_of = _areas.areas_of

# `_proposals_view` USED TO SIT HERE, and it was the panel's own reading of
# `proposals[]` - including a `_parked_blockers` walk that answered the question
# `_proposals.unresolved_refs` already answers. It moved to `_proposals.py`
# (layer 4, imported by `_panel_state` at 5) when `/audit:propose list` stopped
# being prose a model rendered and became a table the script prints: two surfaces
# reading one array two ways is two answers about one manifest. A parked phase is
# also not part of the plan yet, which is why it was never part of the
# composition view even while it lived in this file.


def _bugs_view(manifest):
    """The bug rows the Overview lists, one per bug, already resolved.

    `status` here is the EFFECTIVE status — the same value `rollup()` counts in
    `bugs.byStatus`, computed by the same function — so a reader who clicks the
    "Fixed 2" pill gets exactly two rows. Deriving it a second time in JavaScript
    would be a second implementation of the bug<->task rule (a bug materialized
    into a task reads `fixed` once that task is done), and two implementations
    that can disagree is precisely how the panel's counts and its lists drift.
    `reported` keeps what the manifest actually stores, so a bug whose status is
    inherited from its task can say so instead of looking hand-edited."""
    as_ = _paths.status_facts()
    # The two indexes come from `_manifest_io` — the module that owns the shape —
    # rather than from a walk here; `phase_of_task` is why the enclosing `phases`
    # list this used to build is gone, since nothing else needed the phase bodies.
    # They are guaranteed to share a key set, which is what lets a row read both.
    task_by_id = _mio.tasks_by_id(manifest)
    task_phase = _mio.phase_of_task(manifest)
    out = []
    for b in (manifest.get("bugs") or []):
        if not isinstance(b, dict):
            continue
        eff = _mio.effective_bug_status(b, task_by_id)
        out.append({
            "id": b.get("id"), "title": b.get("title"),
            "status": eff,
            "reported": b.get("status"),
            "severity": b.get("severity"),
            # `open` and `high` are decided HERE, by the same two rules the rollup's
            # `open` / `openHighSeverity` counts use — CLOSED_BUG and the
            # high-or-worse severity set, which knows that critical, blocker, sev1
            # and p0 all mean high. A regex in the browser would be a third opinion
            # on the same question, and the "High severity, open" pill would
            # eventually count a different set than the list it filters to.
            "open": eff not in as_.CLOSED_BUG,
            "high": as_._is_high_severity(b.get("severity")),
            "taskId": b.get("taskId"),
            "phaseId": task_phase.get(b.get("taskId")),
            "reportedAt": b.get("reportedAt"),
        })
    return out


def _skills_of(task):
    """A task's skills as the panel SHOWS them — the THREE states kept apart.

    Explicit `null` is a conscious opt-out ("none applies" — it stops the area
    fallback, v0.37 B1) and stays None, so every display can say so instead of
    rendering it as empty. `[]` and an absent key both mean "unconsidered" and
    read as []; a junk-typed value reads as [] too (the validator names it).
    This is also the value a change row is written against: the client's form
    holds the same three states, so `[] -> [a]` and `null -> [a]` stay two
    different edits rather than a normalisation disagreement — which is the
    original reason this normaliser exists.
    """
    if isinstance(task, dict) and "skills" in task and task["skills"] is None:
        return None
    v = (task or {}).get("skills")
    return v if isinstance(v, list) else []


# `_ado_drift.link_inventory` yields a KIND per row and the banner counts by a
# plural key, so the two vocabularies meet in one table rather than in a
# `kind + "s"` that would invent a key the moment a fourth kind is added.
_LINK_COUNT_KEY = {"phase": "phases", "task": "tasks", "bug": "bugs"}

# The lens that already PRINTS this, and the one command that re-derives it:
# `/audit:sync status` runs `read-ado-links.py`, which is where the
# `SHARED: #<id>` lines come from. THE ONLY LITERAL OF THIS COMMAND IN THIS
# FILE - `_PARENT_OBSERVE` below asks a different question of the same
# invocation and is spelled as this name, because two literals of one command
# name are two commands the day it is renamed.
_LINKS_LENS = "/audit:sync status"


def _claimant(row):
    """One row as the sentence a reader recognises: `phase P1`, `bug BUG-2`.

    The spelling `read-ado-links.claims_shared_by_several` already uses, because
    the panel banner and that command's `SHARED:` line describe one fact and a
    reader who saw both should not have to work out that they agree.
    """
    return "%s %s" % (row.get("kind"), row.get("id"))


def _shared_claims(inventory):
    """{state, items, basis, refresh} — the work items MORE THAN ONE manifest
    item claims.

    THE THREE STATES ARE `_candidate_cache`'S, APPLIED TO A THIRD QUESTION.
    "nothing carries a link here" and "every card is claimed exactly once" both
    reach a banner as an empty list, and a banner that renders them identically
    says the second while meaning the first — a filter narrowed to nothing
    reading as all clear. So the state is NAMED:

      unlinked   nothing in this manifest carries a work-item link, so nothing
                 has been counted. Not agreement; there is nothing to compare
      none       links were walked and each work item is claimed by one item
      shared     at least one work item is claimed by several, and they are named

    WHY THIS IS WORTH A BANNER AT ALL. Nothing validates that a work-item id is
    claimed once: `check_ado_meta` grades the SHAPE of a link and never the
    uniqueness of its target, so an import that adopts a card somebody had
    already linked by hand produces two manifest items pointing at one card, and
    a push then writes both to the same place. Sharing is not always a mistake —
    a bug materialized as a fix task legitimately links one card, which is why
    `_ado_fetch.chunk_ids` de-duplicates rather than refusing — so this NAMES
    what it found and grades nothing.

    IT TAKES THE ROWS AND NOT THE MANIFEST, so the caller's single
    `link_inventory` walk answers both halves of the banner. A second walk here
    would be the two-walks defect `_ado_status` was repaired of.

    A SECOND DERIVATION, AND SAID SO OUT LOUD. `read-ado-links.py` groups its
    own (state-carrying) rows the same way for the `SHARED:` lines it prints;
    that module is an entry point and cannot be imported, so the grouping lives
    twice until it moves down beside `link_inventory` itself. A case in
    `test__panel_composition.py` loads that script and pins the two answers
    equal, because a duplication nothing compares is the one that drifts.
    """
    rows = [r for r in (inventory or []) if isinstance(r, dict)]
    by_ado = {}
    for row in rows:
        by_ado.setdefault(row.get("adoId"), []).append(row)
    # Sorted by work-item id, so a payload regenerated from one manifest is the
    # same payload - `read-ado-links` orders its own `SHARED:` lines the same
    # way, and a banner whose ids reshuffle per process cannot be diffed.
    items = [{"adoId": ado_id,
              "claimants": [_claimant(r) for r in by_ado[ado_id]]}
             for ado_id in sorted(by_ado)
             if len(by_ado[ado_id]) > 1]
    if not rows:
        return {"state": "unlinked", "items": [],
                "basis": "no item in this plan carries a work-item link, so "
                         "nothing has been counted: this is not 'every card is "
                         "claimed once', it is that there is nothing to "
                         "compare yet. It becomes a question the first time a "
                         "push links an item.",
                "refresh": _LINKS_LENS}
    if not items:
        return {"state": "none", "items": [],
                "basis": "%d link(s) walked, and each work item is claimed by "
                         "exactly one item in this plan — counted, not assumed. "
                         "%s prints the same tally."
                         % (len(rows), _LINKS_LENS),
                "refresh": _LINKS_LENS}
    return {"state": "shared", "items": items,
            "basis": "%d work item(s) carry more than one claim in this plan "
                     "(%s). Nothing refuses that — a link's SHAPE is validated "
                     "and the uniqueness of its target never is — so a push "
                     "writes every claimant to the same card and the last one "
                     "wins. %s prints which state each of them would send."
                     % (len(items),
                        "; ".join("#%s claimed by %s"
                                  % (one["adoId"], ", ".join(one["claimants"]))
                                  for one in items),
                        _LINKS_LENS),
            "refresh": _LINKS_LENS}


def _ado_status(manifest):
    """The ADO card's honesty-banner facts — MANIFEST EVIDENCE only, no network.

    The policy tab's rule applied to a second feature: the panel reports what
    the file proves (links /audit:sync wrote), never what the connector claims.
    `enabled`/`echo` are EFFECTIVE values (absent = on; a disabled connector
    reads echo off too) because the banner answers "what happens now", not
    "what is typed".

    THE WALK IS `_ado_drift.link_inventory`, NOT A SECOND ONE. That function is
    what `read-ado-links.py` (the manifest side of every ADO link) and
    /audit:doctor's `ado links` row already ask, and this file used to put the
    same question to the same manifest with its own nested closure - including
    its own copy of the int-and-not-bool id guard the validator holds. Two walks
    over one file is two answers waiting to disagree, and the panel's copy was
    the one with no cases of its own about link SHAPES.

    STILL OFFLINE, which is the property the banner is built on and the reason
    this edge is safe to add: `link_inventory` reads the loaded manifest dict and
    `_manifest_io.iter_tasks`, and touches no board. The fetch lives in
    `fetch-ado-items.py`, which nothing here reaches.

    Phases are walked directly and tasks through `_mio.iter_tasks` — inside
    `link_inventory` now, but for the reason that has always applied here: a
    phase can carry an `ado` link with no tasks under it at all, and
    `iter_tasks` yields nothing for such a phase.

    `shared` IS THE HALF ONLY THAT WALK CAN ANSWER, and it is here rather than
    beside the counts because it is the same rows read a second way: which work
    items MORE THAN ONE manifest item claims. `_shared_claims` says what its
    three states are for.
    """
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado")
    configured = isinstance(ado, dict)
    ado = ado if configured else {}
    enabled = configured and ado.get("enabled") is not False
    linked = {"tasks": 0, "bugs": 0, "phases": 0}
    last = None
    # ONE walk, read twice. The counts and the shared-claim grouping are two
    # questions about the same rows, and calling `link_inventory` again for the
    # second would put back exactly the two-walks defect this function was
    # repaired of - with the added trap that the two could then be walked over
    # different manifests.
    inventory = _drift.link_inventory(manifest)
    for row in inventory:
        # A KIND WITH NO CELL GETS ITS OWN, rather than being skipped or folded
        # into a neighbour. Dropping it would leave the banner reporting fewer
        # links than the manifest carries with nothing to say so, and adding it
        # to "tasks" would inflate a number the operator reads as evidence. A
        # new key is the only option that neither loses the row nor lies about
        # it; a case pins the table against the kinds `link_inventory` emits, so
        # this branch is the runtime half of a mismatch the build already fails.
        key = _LINK_COUNT_KEY.get(row.get("kind"), row.get("kind"))
        linked[key] = linked.get(key, 0) + 1
        link = row.get("link") or {}
        ts = link.get("lastSyncedAt")
        if isinstance(ts, str) and (last is None or ts > last):
            last = ts
    return {"configured": configured,
            "enabled": enabled,
            "echo": enabled and ado.get("echo") is not False,
            "linked": linked, "lastSyncedAt": last,
            "shared": _shared_claims(inventory)}


# --- where a phase hangs on the board, as the Composition table shows it --------
# The command that re-derives the candidate cache, spelled once: it appears in
# every state's sentence below, and three copies of a command name is three
# commands the day one of them is renamed.
_PARENT_REFRESH = "/audit:sync parents"

# The command that ASKS THE BOARD where one item hangs - a different question
# from the one above, and named separately because the two are one word apart in
# a sentence and a reader sent to the wrong one learns nothing. `parents` caches
# the candidate list and the backlog ranks and touches no item's own link;
# `status` fetches `System.Parent` and prints the verdict, writing nothing.
#
# It is the SAME invocation as `_LINKS_LENS`, and it is spelled as that name
# rather than retyped: two questions may deserve two names, and one command
# still deserves one literal.
_PARENT_OBSERVE = _LINKS_LENS


# --- the branch-naming convention, as the Composition card shows it -------------
def _branch_info(manifest):
    """The naming convention as it CURRENTLY resolves, plus a worked example.

    The example is computed HERE, in Python, from the value on disk — not in the
    browser as the operator types. A live preview would mean a second
    implementation of `_branch.expand`, whose whole point is a separator rule with
    cases; two copies of that is two answers, and the first time they disagree the
    branch git actually gets is the one nobody previewed. So the card shows what
    the SAVED settings produce, and the save re-renders it.

    `basis` rides along because `meta.branch` and `meta.branchPrefix` give
    different names from the same manifest, and a card that showed the template
    without saying which key was in force would be describing a convention that
    might not be the one running.
    """
    meta = manifest.get("meta") or {}
    cfg = _branch.config(meta)
    # A phase from the plan when there is one, so the example is THIS repo's, not
    # a stranger's. The fallback is labelled as an example rather than dressed up
    # as real - naming a phase that does not exist would be the more confusing half.
    sample = None
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") and ph.get("title"):
            sample = ph
            break
    made = _branch.compose(meta, sample or {"id": "P2", "title": "Chart export"},
                           initials="Jane Doe")
    return {
        "template": cfg["template"],
        "defaultType": cfg["defaultType"],
        "types": cfg["types"],
        "initials": cfg["initials"],
        "slugMaxLength": cfg["slugMaxLength"],
        "basis": cfg["basis"],
        "typeHelp": dict(_branch.TYPE_HELP),
        "example": made["name"],
        "exampleFrom": (sample or {}).get("id") or "P2 (no phase in the plan yet)",
        "exampleInitials": "Jane Doe",
        "violations": made["violations"],
    }


def _ado_parent_of(phase):
    """One phase's declaration, with ABSENT spelled as the marker.

    The three stored states are absent, null and an object, and the panel has to
    offer all three. A payload that simply left the key off would hand the
    browser `undefined` for absent and `null` for the declared nowhere - and
    `undefined` reads as "the server did not say", which is a fourth thing. So
    absent is spelled with `_ado_parent`'s own marker, the same object the patch
    sends back for it, and the browser reads one value with three shapes.
    """
    if _ado_parent.FIELD in phase:
        return phase.get(_ado_parent.FIELD)
    return _ado_parent.use_fallback()


def _candidate_row(item):
    """One cached candidate, or None when it carries no usable id.

    Int-only, `bool` refused first - the shape `_manifest_ado` grades and the
    same guard `_ado_status` applies to a link id, so junk in the cache cannot
    put an option in a menu that would be refused the moment it was saved.
    """
    if not isinstance(item, dict):
        return None
    wid = item.get("id")
    if isinstance(wid, bool) or not isinstance(wid, int) or wid <= 0:
        return None
    return {"id": wid, "type": item.get("type"), "title": item.get("title"),
            "state": item.get("state"), "url": item.get("url")}


def _candidate_cache(ado):
    """(state, rows, fetchedAt, basis) for `meta.ado.parentCandidates`.

    THE TWO EMPTIES ARE DIFFERENT ANSWERS AND THIS IS WHERE THEY SEPARATE.
    "nobody has fetched a list" and "the board had no parent-shaped item in
    scope" both reach a picker as zero options, and a menu that renders them
    identically says the second while meaning the first - a filter narrowed to
    nothing reading as all-clear. So the state is NAMED and each name carries
    the sentence that makes it checkable: the moment somebody looked, and the
    query that scoped the look.

    The manifest's own `basis` is quoted rather than paraphrased, and its
    ABSENCE is reported rather than papered over: a cache with no basis has to
    be trusted instead of checked, and saying so is the only honest option.
    """
    block = ado.get("parentCandidates")
    if not isinstance(block, dict):
        return ("absent", [], None,
                "no candidate list has been cached: nobody has asked this board "
                "yet, which is not the same answer as a board carrying no "
                "parent-shaped work item. Run %s to fetch one; until then a "
                "parent is named by typing its id." % (_PARENT_REFRESH,))
    rows = [r for r in [_candidate_row(x)
                        for x in (block.get("items") or [])] if r]
    fetched = block.get("fetchedAt")
    fetched = fetched if isinstance(fetched, str) and fetched else None
    declared = block.get("basis")
    declared = declared if isinstance(declared, str) and declared.strip() else None
    when = (" fetched %s" % (fetched,)) if fetched else " fetched at no recorded moment"
    # The stop is put back rather than assumed: the manifest's `basis` is
    # somebody else's sentence and may or may not carry one, and the clause that
    # follows it is a new sentence either way.
    how = ((" Scoped by: %s." % (declared.rstrip("."),)) if declared else
           (" The fetch recorded no basis, so how it was scoped is unknown - an "
            "empty list here cannot be told from a narrowed one."))
    if not rows:
        return ("empty", rows, fetched,
                "the cached candidate list is empty:%s, this board carried no "
                "parent-shaped work item in scope.%s Re-run %s to look again."
                % (when, how, _PARENT_REFRESH))
    return ("items", rows, fetched,
            "%d cached candidate(s),%s.%s Cached evidence and never an "
            "authority: an id missing from this list is not a wrong parent, "
            "only one created since the fetch. Re-run %s to refresh it."
            % (len(rows), when, how, _PARENT_REFRESH))


# The command that re-derives the connection evidence. Spelled once, beside
# `_PARENT_REFRESH` and for the same reason.
_CONNECT_REFRESH = "/audit:sync connect"


def _ado_connection(manifest):
    """What `/audit:sync connect` PROVED about this board, for the ADO card.

    THE CARD CANNOT RUN CONNECT AND MUST NOT PRETEND OTHERWISE. `connect`
    authenticates, and the panel authenticates nothing - so this is the same
    kind of block `_candidate_cache` is: manifest evidence, read-only, with the
    moment and the basis kept, and the command that re-derives it named in
    every state.

    WHY THE CARD SHOWED NOTHING ABOUT THIS BEFORE. `meta.ado.stateMap` is the
    single most likely first-push failure - the shipped defaults name Agile
    states, and a Scrum board refuses them - and the card let you edit the map
    while saying nothing about which process the board runs. The probe knows.
    So the `needs-map` state exists to put that answer where the control is,
    rather than in a terminal the person editing this card never saw.

    Four named states, because the ways of knowing nothing are not one way:
      absent     - connect has never run here.
      unknown    - it ran and could not tell which process (empty project, no
                   phase-level item yet, or two of them).
      needs-map  - it ran, this board is not Agile, and `stateMap` is not set.
      ok         - it ran, and nothing about the process is outstanding.
    """
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    block = ado.get("connection")
    if not isinstance(block, dict):
        return {"state": "absent", "process": None, "pbiType": None,
                "authPath": None, "fetchedAt": None,
                "basis": "this board has never been probed: nobody has run %s "
                         "here, so which process it runs - and therefore "
                         "whether stateMap is needed - is unknown rather than "
                         "settled. The connector may still be configured and "
                         "working; what is missing is the evidence, not the "
                         "connection." % (_CONNECT_REFRESH,),
                "refresh": _CONNECT_REFRESH}
    process = block.get("process")
    process = process if isinstance(process, str) and process else None
    pbi = block.get("pbiType")
    pbi = pbi if isinstance(pbi, str) and pbi else None
    auth = block.get("authPath")
    auth = auth if isinstance(auth, str) and auth else None
    fetched = block.get("fetchedAt")
    fetched = fetched if isinstance(fetched, str) and fetched else None
    when = ((" probed %s" % (fetched,)) if fetched
            else " probed at no recorded moment")
    # The auth PATH, never a credential and never a who: the card is a shared
    # screen, and the only useful fact here is which KIND of credential a later
    # 401 would be about.
    via = ((" Access was proven through the %r auth path." % (auth,)) if auth
           else " Which auth path answered was not recorded.")
    if process is None:
        return {"state": "unknown", "process": None, "pbiType": None,
                "authPath": auth, "fetchedAt": fetched,
                "basis": "access was proven,%s, but the process template could "
                         "not be told from this board - an empty project, one "
                         "carrying no phase-level item yet, or a customised "
                         "one carrying two.%s Until it is known, the shipped "
                         "stateMap defaults name Agile states and nothing here "
                         "says whether that fits. Re-run %s once the board has "
                         "a phase-level item on it."
                         % (when, via, _CONNECT_REFRESH),
                "refresh": _CONNECT_REFRESH}
    if block.get("stateMapNeeded") is True and ado.get("stateMap") is None:
        return {"state": "needs-map", "process": process, "pbiType": pbi,
                "authPath": auth, "fetchedAt": fetched,
                "basis": "this board runs the %s process,%s, and stateMap is "
                         "not set. The built-in defaults name Agile states, so "
                         "a task reaching done will be refused its state - set "
                         "the map below.%s"
                         % (process, when, via),
                "refresh": _CONNECT_REFRESH}
    return {"state": "ok", "process": process, "pbiType": pbi,
            "authPath": auth, "fetchedAt": fetched,
            "basis": "this board runs the %s process,%s; phase items are %s.%s "
                     "Cached evidence, so re-run %s after the board's process "
                     "or your credential changes."
                     % (process, when, ("%r" % (pbi,)) if pbi else "unrecorded",
                        via, _CONNECT_REFRESH),
            "refresh": _CONNECT_REFRESH}


def _ado_parents(manifest):
    """What the per-phase parent control needs, each half with its basis.

    `fallback` carries the ID AND THE SOURCE and deliberately not the sentence:
    `resolve` phrases its basis around the item it was asked about, and this
    call has no item - it asks the fallback question with an empty one. The
    sentence that names a phase is on that phase's own row, where it is true.
    Nothing here re-reads `parentWorkItem`: a second read would be a second
    opinion about where work hangs, which is what `resolve` exists to prevent.
    """
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    fallback = _ado_parent.resolve({}, ado)
    state, rows, fetched, basis = _candidate_cache(ado)
    return {"fallback": {"id": fallback["id"], "source": fallback["source"]},
            "candidates": rows, "fetchedAt": fetched,
            "cache": state, "basis": basis, "refresh": _PARENT_REFRESH}


def _resolved_parent(phase, ado):
    """`{id, source, basis}` for one phase - `resolve`'s answer, minus what a
    row cannot use. The declaration is already on the row and the warnings are
    the push plan's, so what is left is the answer and the sentence behind it."""
    res = _ado_parent.resolve(phase, ado)
    return {"id": res["id"], "source": res["source"], "basis": res["basis"]}


def _board_parent(phase):
    """What the BOARD says about this phase's parent - and the two ways of not
    knowing, which the cell used to render as agreement.

    THE PANEL ASKS NO BOARD AND MUST NOT. This is `_candidate_cache`'s shape
    applied to a second question, for exactly its reason: the declaration is
    already painted here and a reader takes it for the answer, so a cell that
    looks the same whether the board agrees or was never asked SAYS agreement
    while MEANING silence.

    NOTHING CACHES AN OBSERVED PARENT PER ITEM, and that is the answer rather
    than a gap to fill with a default. `/audit:sync status` fetches
    `System.Parent`, prints its verdict and writes nothing; `/audit:sync
    parents` caches the candidate list and the backlog ranks and touches no
    item's own link. The single board-derived thing an item can carry is a
    declaration a PULL wrote - `source: "imported"`, with the moment it was
    seen - and that is a record of one instant, never a live reading.

    Three named states, because the ways of not knowing are not one way:
      unlinked     nothing of this phase is on the board yet, so nothing there
                   hangs anywhere and the declaration is a plan for a create
      observed     the declaration came OFF the board, at `observedAt`
      never-asked  it IS linked, and nothing here records where the board hangs
                   it
    """
    where = (phase.get("id") if isinstance(phase, dict) else None) or "this phase"
    link = _ado_parent._work_item_id(phase)
    if link is None:
        return {"state": "unlinked", "id": None, "observedAt": None,
                "basis": "%s has no work item on this board yet, so nothing on "
                         "the board hangs anywhere: the declaration beside this "
                         "is a plan for the create rather than a difference "
                         "from the board. It becomes a question the first time "
                         "a push creates the item." % (where,),
                "refresh": _PARENT_OBSERVE}
    declared = phase.get(_ado_parent.FIELD) if isinstance(phase, dict) else None
    declared = declared if isinstance(declared, dict) else {}
    seen = declared.get("observedAt")
    seen = seen if isinstance(seen, str) and seen else None
    # A positive id is required before this is called an observation: a pull
    # that wrote an unusable id recorded nothing readable, and reporting it as
    # what the board said would be a claim with no basis under it. Such a phase
    # falls through to `never-asked`, whose sentence is true of it.
    observed = _ado_parent._positive_id(declared.get("id"))
    if declared.get("source") == "imported" and observed is not None:
        return {"state": "observed", "id": observed, "observedAt": seen,
                "basis": "the board hung %s under #%d when a pull read it%s - "
                         "`source: \"imported\"` is the one board-derived "
                         "answer a manifest keeps, and it is a record of that "
                         "moment and not a live reading. Run %s to compare it "
                         "with the board as it is now."
                         % (where, observed,
                            (", at %s" % (seen,)) if seen
                            else ", at no recorded moment",
                            _PARENT_OBSERVE),
                "refresh": _PARENT_OBSERVE}
    return {"state": "never-asked", "id": None, "observedAt": None,
            "basis": "nothing here records where the board hangs %s's work item "
                     "#%d: no command caches an observed parent per item, so "
                     "the value beside this is what somebody DECLARED and not "
                     "what the board answered. %s asks the board and prints "
                     "the comparison; until it is run, the two agreeing and "
                     "nobody having looked are the same picture."
                     % (where, link, _PARENT_OBSERVE),
            "refresh": _PARENT_OBSERVE}


# --- whether a phase is on the board AT ALL, as the Composition table shows it --
# A DIFFERENT QUESTION FROM THE ONE ABOVE, and it comes first in the reading
# order: where a phase hangs is only a question once it belongs on the board.
# `_ado_tracked` owns the rule and nothing here re-derives it - the push plan,
# the status lens and `resolve-ado-tracked.py` all ask that module, and a panel
# holding its own opinion about what belongs on a shared board would be a second
# policy wearing a control.
def _ado_tracked_of(phase):
    """One phase's own declaration, with ABSENT spelled `null`.

    NULL IS SAFE HERE AND IS NOT SAFE FOR `adoParent`, which is why this is not
    `_ado_parent_of` with another field name. There, `null` is a VALUE - "hangs
    under nothing, on purpose" - so absent needed a marker of its own or the two
    answers that differ most would have reached the browser as one. `adoTracked`
    is `"type": "boolean"` in the schema, so `null` is not a value it can carry
    and the key's absence is the only thing it can mean. The patch spelling is
    the same `null`, which is what makes the round trip readable: what the row
    shows for "nothing declared" is exactly what a save sends to put it back.

    A value that is neither boolean nor absent travels VERBATIM rather than
    being folded into either. `declared()` refuses to read it and `resolve`
    answers "no basis", so the control has to be able to say the same - and a
    payload that had already flattened it to absent would have the control
    painting the default over somebody's broken declaration, which is the
    confident wrong answer this whole key exists to remove.
    """
    if _ado_tracked.FIELD in phase:
        return phase.get(_ado_tracked.FIELD)
    return None


def _resolved_tracked(phase, ado):
    """`{tracked, basis}` for one phase - `resolve`'s answer, minus what a row
    cannot use.

    `_resolved_parent`'s shape and its reason: the declaration is already on the
    row and the warnings belong to the push plan, so what is left is the answer
    and the sentence behind it. `tracked` is THREE-VALUED and stays that way all
    the way to the browser - True, False, and None for "nothing here has a basis
    to say" - because a None rendered as either boolean is the false confidence
    the feature was built to end.
    """
    res = _ado_tracked.resolve(phase, ado)
    return {"tracked": res["tracked"], "basis": res["basis"]}


# --- whether a run was recorded, and whose gate would have graded it ----------
# THE POINTER IS A CACHE AND THE LEDGER IS THE TRUTH -- `_evidence_io`'s own
# contract, and the reason both travel to the browser instead of one folded
# answer. The row carries what the PLAN claims; `evidence_view` carries what the
# LEDGER holds. Folding them here would have to pick one, and the case a reader
# most needs to see is exactly the one where they disagree.
def _pointer_of(node):
    """`testEvidence` as the manifest carries it, or None when it carries none.

    ABSENT MEANS NO RUN WAS RECORDED, NEVER 'FAILED'. The schema says so at the
    field, and it is the one reading of a silence that costs somebody a night -- a
    manifest written before this field existed, a task nobody has run, and a block
    somebody deleted are one state. So the key is READ and never defaulted, and
    nothing here invents a verdict for a subject that has none.

    A block that is present but is not an object travels AS IT IS, for
    `_ado_tracked_of`'s reason one field over: flattening it to absent would have
    the badge painting 'nothing recorded' over somebody's broken declaration,
    which is the confident wrong answer this whole field exists to remove.
    """
    return node.get(_ev.POINTER_KEY)


def _gate_source(phase, task=None):
    """`"task"`, `"phase"` or None -- whose gate would grade this subject.

    A SECOND EXPRESSION OF `run-test-gate.gate_of`'s resolution, and it is spelled
    here rather than imported because that file is an entry point at layer 7 while
    this module sits at 4: importing it would be an upward edge the layer lint
    fails by name. What keeps the two honest is not this paragraph --
    `tests/test__panel_composition.py` drives both over one table of subjects and
    goes red when they disagree.

    ABSENT, EMPTY AND ALL-BLANK ARE ONE ANSWER, which is `gate_of`'s own rule: a
    task with no `tests` block and a task with `tests.gate: []` both declare no
    gate, and making them two answers would be two chances to disagree about one
    question. The fallback direction is `gate_of`'s too -- a task declaring
    nothing is graded by the PHASE's gate, and 'this task's gate passed' and 'the
    phase's gate passed while pointed at this task's files' are different claims a
    badge must not merge.

    None is NOT 'nothing ran'. It is 'nothing could have run', which is the
    sentence `No gate configured` says and the one `No evidence` does not.
    """
    if task is not None:
        tests = task.get("tests")
        entries = (tests.get("gate") or []) if isinstance(tests, dict) else []
        if any(isinstance(e, str) and e.strip() for e in entries):
            return "task"
    if any(isinstance(e, str) and e.strip()
           for e in (phase.get("testGate") or [])):
        return "phase"
    return None


# The positional columns of one evidence fact row, and of one step inside it. The
# client reads its rows against these lists, so the two travel together in the
# payload -- `_panel_usage._FACT_FIELDS`'s shape, for its reason: what the browser
# receives is what the run OBSERVED, and every badge, marker and sentence on the
# page is re-derived from that rather than being a verdict the server wrote.
EVIDENCE_FIELDS = ("runId", "scope", "status", "at", "attempt", "durationMs",
                   "ranTotal", "countsBasis", "treeMutated", "treeBasis",
                   "coverage", "coverageBasis", "steps")
EVIDENCE_STEP_FIELDS = ("name", "exit", "ran", "durationMs", "outcome")


def _evidence_steps(row):
    """Each recorded step as a positional row, in the order the run ran them.

    Bounded by what the ledger already bounded (`_evidence_io.MAX_STEPS`), so
    nothing here re-cuts a list somebody else already cut and counted.

    NEITHER `command` NOR `commandSha256` CROSSES. A step's command is either the
    manifest's own published string or a digest of an ad-hoc one, and a badge in a
    table renders neither; shipping it would put a command on a surface that has
    no room to say which of the two it is.
    """
    out = []
    for step in (row.get("steps") or []):
        if isinstance(step, dict):
            out.append([step.get(k) for k in EVIDENCE_STEP_FIELDS])
    return out


def _count_or_unknown(value):
    """`len(value)` for a list, None for anything else -- and None means UNKNOWN.

    The direction is the whole point. `treeMutated` and `coverage` are
    three-valued in the ledger: `[]` is 'compared, and there was nothing', a list
    is the finding, and None is 'no comparison was made'. `len(value or [])` maps
    all three onto a number and calls the third one clean, which is the merge
    `run-test-gate.render` refuses to make and the reason its basis lines exist.
    Anything that is neither None nor a list lands on None as well: a value this
    function cannot count is a value it has no basis to call clean.
    """
    return len(value) if isinstance(value, list) else None


def _evidence_facts(row):
    """One recorded run as a positional fact row, read against EVIDENCE_FIELDS.

    THE LISTS BECOME COUNTS AND THE BASES TRAVEL WHOLE. A count answers 'is there
    a marker'; the basis answers 'why is this unknown'; the paths themselves are
    the one part no badge ever renders, and a table with no room for them would
    have to truncate a list the ledger deliberately kept.

    A row with no `observations` block answers UNKNOWN to all three questions
    rather than answering zero. That is the honest reading: the block is what
    `_evidence_io.row_for` writes every observation into, so its absence means
    nobody wrote one down -- not that nothing was found.
    """
    obs = row.get("observations")
    obs = obs if isinstance(obs, dict) else {}
    return [row.get("runId"), row.get("scope"), row.get("status"), row.get("ts"),
            row.get("attempt"), row.get("durationMs"),
            obs.get("ranTotal"), obs.get("countsBasis"),
            _count_or_unknown(obs.get("treeMutated")), obs.get("treeBasis"),
            _count_or_unknown(obs.get("coverage")), obs.get("coverageBasis"),
            _evidence_steps(row)]


def empty_evidence():
    """The `evidence` payload for a project whose plan points at nothing.

    ONE SHAPE FOR EVERY EXIT, which is `_panel_usage._usage_shape`'s reason: a key
    spelled in one branch and forgotten in the other is an `undefined` that only a
    fresh install ever meets -- i.e. only the reader least placed to report it.

    `files` and `unreadable` are zero here rather than absent because no pointer
    exists on this path, so nothing reads them; the moment a pointer does exist,
    `evidence_view` replaces both with what the ledger actually answered.
    """
    return {"fields": list(EVIDENCE_FIELDS),
            "stepFields": list(EVIDENCE_STEP_FIELDS),
            "runs": {}, "files": 0, "unreadable": 0}


def evidence_view(project, composition, config=None):
    """The recorded runs the plan POINTS AT, as facts the browser re-aggregates.

    Keyed by `runId` and cut to the pointers the composition rows already carry,
    because that is the whole of what a badge needs: every other row in the ledger
    is history, and shipping the history would put an unbounded file on every
    `/api/state`. It is handed the composition rather than the manifest for the
    same economy -- the pointers are on those rows, and a second walk over the
    plan would be a second answer to 'which runs does this plan name'.

    `files` and `unreadable` ride along and are not decoration. A pointer whose
    run is not here is a real state with a sentence of its own -- the plan names a
    run the ledger does not hold -- and a reader cannot tell an evidence directory
    that was never written from one whose lines could not be parsed unless both
    counts are on the page. `read_rows` counts a torn line rather than dropping it
    in silence for exactly that reason.

    The ledger is read WHOLE and cut afterwards: `read_rows` is the one walk over
    it, and a filtered read written here would be a second opinion about what is
    in the directory.
    """
    wanted = set()
    for group in ("phases", "tasks"):
        for row in (composition.get(group) or []):
            pointer = row.get(_ev.POINTER_KEY)
            run_id = pointer.get("runId") if isinstance(pointer, dict) else None
            if isinstance(run_id, str) and run_id:
                wanted.add(run_id)
    read = _ev.read_rows(project, config=config)
    newest = {}
    for row in read["rows"]:
        run_id = row.get("runId")
        if run_id not in wanted:
            continue
        current = newest.get(run_id)
        # `latest_by_subject`'s comparison, one key over: two worktrees write two
        # files whose concatenation is in no meaningful order, so reading position
        # would make 'the run' depend on a directory listing.
        if current is None or (str(row.get("ts") or "")
                               >= str(current.get("ts") or "")):
            newest[run_id] = row
    out = empty_evidence()
    out["runs"] = dict((k, _evidence_facts(v)) for k, v in newest.items())
    out["files"] = read["files"]
    out["unreadable"] = read["unreadable"]
    return out


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    phases_out, tasks_out = [], []
    # `phases_out` and `tasks_out` are separate flat lists, so splitting the old
    # nested walk in two changes neither one's order: the phase rows stay in
    # document order and `_mio.iter_tasks` yields the tasks in document order too.
    # The task rows need the owning phase's id, which arrives with the task.
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        review = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        phases_out.append({"id": ph.get("id"), "title": ph.get("title"),
                           "status": ph.get("status"), "reviewModel": review.get("model"),
                           "area": _areas_of(ph.get("area")), "reviewSkill": ph.get("reviewSkill"),
                           # Through `_priority.tier_of`, never off the raw field:
                           # a value that is not a positive integer orders nothing,
                           # and a control showing it as a tier would offer to keep
                           # a pin the run does not honour.
                           "priority": _priority.tier_of(ph),
                           # Both halves, because neither is the other. The
                           # DECLARATION is what a control edits and what a save
                           # sends back; the RESOLUTION is what the phase
                           # actually hangs under right now, which for an absent
                           # declaration is the fallback and for an unusable one
                           # is nothing at all. A control showing only the first
                           # would let a reader edit a field without seeing what
                           # it currently does.
                           "adoParent": _ado_parent_of(ph),
                           "adoParentResolved": _resolved_parent(ph, ado),
                           # THE THIRD HALF, and it is the one that was missing
                           # (F101). Both values above are read out of the
                           # manifest, so a row whose board was never asked and
                           # a row the board agrees with painted the same
                           # pixels - which is the shape this repo has recorded
                           # under several other names. This says which of the
                           # two it is, without asking a board.
                           "adoParentBoard": _board_parent(ph),
                           # THE QUESTION BEFORE ALL THREE OF THOSE: does this
                           # phase belong on the board at all. Both halves for
                           # `adoParent`'s reason - the DECLARATION is what the
                           # control edits and what a save sends back, and the
                           # RESOLUTION is the answer in force, which for an
                           # absent declaration is the default said out loud and
                           # for an unreadable one is nothing at all.
                           "adoTracked": _ado_tracked_of(ph),
                           "adoTrackedResolved": _resolved_tracked(ph, ado),
                           # BOTH HALVES AGAIN, and here they are two different
                           # silences rather than a declaration and its
                           # resolution. The POINTER alone cannot tell 'nobody
                           # has run this phase's sign-off gate' from 'there is
                           # no gate here to run', and a reader acts on those in
                           # different places -- one is work not done, the other
                           # is a plan that can never prove itself done.
                           "testEvidence": _pointer_of(ph),
                           "gateSource": _gate_source(ph)})
    for ph, t in _mio.iter_tasks(manifest):
        tasks_out.append({
            "id": t.get("id"), "title": t.get("title"),
            "phaseId": ph.get("id"), "status": t.get("status"),
            "model": t.get("model"),
            "skills": _skills_of(t),
            # ov (F-P-5): Overview shows what the REPORT's table shows, so
            # it needs the same four values. They ride the composition
            # payload rather than a second endpoint — this is one manifest
            # read either way, and the Composition tab ignores what it does
            # not edit. Timestamps stay whole; the client cuts them.
            "risk": t.get("risk"),
            "commit": t.get("commit"),
            "startedAt": t.get("startedAt"),
            "completedAt": t.get("completedAt"),
            # The pointer this task carries, and whose gate would have produced
            # it. `gateSource` is what separates the two silences: a task with a
            # gate and no pointer has not been run, and a task with neither could
            # not have been. `status` above is what the PLAN says happened;
            # this is whether anything measured it.
            "testEvidence": _pointer_of(t),
            "gateSource": _gate_source(ph, t),
        })
    # Every skill name the AREAS declare, deduped in registry order — the other
    # half of what the manifest spells (task rows carry their own). Shipped so
    # the client's inventory hint (skillHints, the modelHints analog) can see
    # a name that lives only in meta.areas without a second endpoint.
    area_skills = []
    for entry in _areas.registry(manifest).values():
        sk = entry.get("skills")
        for s in (sk if isinstance(sk, list) else []):
            if isinstance(s, str) and s.strip() and s.strip() not in area_skills:
                area_skills.append(s.strip())
    return {
        "meta": {"reviewSkill": meta.get("reviewSkill"),
                 "buildCommands": meta.get("buildCommands"),
                 "branch": meta.get("branch"),
                 "ado": meta.get("ado")},
        "areaSkills": area_skills,
        "adoStatus": _ado_status(manifest),
        "adoParents": _ado_parents(manifest),
        "adoConnection": _ado_connection(manifest),
        "branchInfo": _branch_info(manifest),
        "phases": phases_out, "tasks": tasks_out,
    }


def areas_state(project):
    """`GET /api/areas` — the registry, and every tag the phases actually use.

    Both halves, because the two disagree in both directions and each disagreement
    is worth seeing: a tag no entry covers resolves to no reviewer and no skills
    (usually a typo), and a registered area no phase uses is either a plan that has
    not been written yet or a rename that only got done on one side.

    Every verdict here comes from `_areas` — the same module the validator, the
    doctor and the status renderer resolve through — so this endpoint cannot
    develop its own opinion about what is registered.
    """
    config = read_config(project)
    mpath = _manifest_path(project, config)
    out = {"path": _output.posix_rel(mpath, project) if _within(project, mpath)
           else None,
           "areas": {}, "tags": [], "findings": [], "warnings": []}
    if not _within(project, mpath):
        out["findings"] = ["refused: manifest path escapes project"]
        return out
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        out["findings"] = ["cannot read manifest: %s" % exc]
        return out
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    stored = meta.get("areas")
    out["areas"] = stored if isinstance(stored, dict) else {}
    f, w = _areas.validate_registry(stored)
    out["findings"], out["warnings"] = f, w
    reg = _areas.registry(manifest)
    used = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for tag in _areas.areas_of(ph.get("area")):
            used.setdefault(tag, []).append(ph.get("id"))
    for tag in sorted(set(reg) | set(used)):
        entry = reg.get(tag) or {}
        root = _areas.root_of(entry)
        out["tags"].append({
            "tag": tag,
            "registered": tag in reg,
            "phases": used.get(tag, []),
            "root": root or None,
            # Resolved here rather than in the browser: the panel already learned
            # once (c6) that a value it SHOWS and a value the server computes have
            # to come from one function or the two eventually disagree.
            "rootExists": bool(root) and os.path.isdir(os.path.join(project, root)),
            "description": entry.get("description"),
            "reviewSkill": entry.get("reviewSkill"),
            "skills": entry.get("skills") if isinstance(entry.get("skills"), list)
            else [],
        })
    return out


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_composition.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__panel_composition.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
