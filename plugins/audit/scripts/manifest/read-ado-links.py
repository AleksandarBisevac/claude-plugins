#!/usr/bin/env python3
"""
The manifest side of every ADO link: which items carry one, and what state each means.

WHY IT EXISTS. `/audit:sync` had two steps the orchestrator was told to perform
itself, in prose, and prose got both of them wrong on a real board.

  * "Resolve and read the manifest", then "count linked vs unlinked". The obvious
    read is the file at `manifestPath`, and on the sharded layout that file is an
    INDEX whose phases are stubs: the tasks, and every `ado` link on them, live in
    the phase shards beside it. Measured on one manifest: a raw read reached two
    work-item ids and no phase statuses where the loader reached sixty-nine and ten.
    It does not error, it under-counts, and the connector line then reports a
    linked/unlinked split that is wrong on both sides with nothing to suggest it.
  * "Add `mapped` to each entry" - the manifest status translated through
    `meta.ado.stateMap`. `status` step 3 was never told to do it, so on that same
    manifest every drift row read `state not compared (no mapped state supplied)`.

THE SECOND ONE IS WORSE THAN IT LOOKS, and it is the reason this is a door rather
than another paragraph. `_ado_drift.summarize()` counts an overwrite only for a row
whose STATE differs, so a payload carrying no `mapped` reports `0 would overwrite a
change made after our last sync` - the one number the push confirm gate exists for -
on a board where the true answer was never computed. A zero that is structurally
unreachable reads exactly like good news.

THE BUG STATUS IS THE EFFECTIVE ONE, which is the half no prose reader would have
applied. `_manifest_io.effective_bug_status` derives `fixed` from a materialized fix
task that is done, and lets a human `wontfix` win over everything; the raw
`bug.status` of such a bug is still `open`, so a hand translation would map a fixed
bug to `New` and then report the board's `Resolved` card as ours to overwrite.

ONE CARD, TWO CLAIMANTS IS NOT A TIE THIS BREAKS. Nothing refuses two manifest
items linking to the same work item - `check_ado_meta` grades the shape of a link
and never the uniqueness of its target - so an import that adopts a card somebody
had already linked by hand produces exactly that. Where the two mean the same
state the entry is stamped and the duplicate is still named; where they do not,
the entry is left UNSTAMPED and both claimants are printed, because picking the
one the walk reached first would push one item's status onto a card the other one
owns, silently and from a table that looks ordinary.

DELIBERATELY OFF THE BOARD IS NOT THE SAME AS MISSING, and the connector line used
to print it as if it were. `unlinked` was a SUBTRACTION - everything the manifest
holds, minus everything that carries a link - so a phase whose plan says it does
not belong on a shared board reported as unlinked on every run, for ever, and so
did every task under it. That is a false positive with no expiry, and a lens
carrying permanent rows stops being read. `_ado_tracked` owns the rules and the
task inheritance; this file counts a THIRD class off them, never a fourth reading
of the key.

WHAT IT DOES NOT DO. It never calls a board: `fetch-ado-items.py` reads the ADO side
and `explain-ado-drift.py` joins the two. It is read-only, so `meta.ado.enabled:
false` does not gate it - that flag stops writes, and `status` is the lens you need
to decide whether to re-enable. It needs no `meta.ado` at all: with none, every
translation falls back to the built-in defaults and each row says so.

Exit codes:
  0 - answered
  1 - `--items` was given, the payload was NOT empty, and not one entry could be
      given a state. Everything downstream of that is a comparison with no basis,
      and the count the confirm gate reads would be zero for that reason alone.
  2 - usage error, or a manifest/payload that could not be read

Usage:
  read-ado-links.py <manifest>                                   # the inventory
  read-ado-links.py <manifest> --json
  read-ado-links.py <manifest> --items fetched.json --out mapped.json

The `--out` payload is exactly what `explain-ado-drift.py --items` reads, with
`mapped` filled in. `--items` without `--out` is a usage error on purpose: a run
that reported a translation and wrote nothing is one flag away from handing the
UNSTAMPED payload downstream, which is the defect this command exists to end.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_read_ado_links.py`.
"""
import json
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

import _ado_drift as _drift  # noqa: E402  (link_inventory: the ONE walk over links)
import _ado_tracked as _tracked  # noqa: E402  (the ONE answer about belonging)
import _manifest_io as _mio  # noqa: E402  (the loader, the task index, bug status)

USAGE = ("usage: read-ado-links.py <manifest> [--items <file.json|-> "
         "--out <file.json>] [--json]\n")

# Phases first, the order `_ado_drift.link_inventory` walks in, so a row that
# disappears is visible as a missing KIND and not merely as a smaller number.
KINDS = ("phase", "task", "bug")

# --- the table `commands/sync.md` used to own ------------------------------------
# It is here now because a table in prose cannot be applied by anything but a
# reader, and two readers applied it differently: `status` step 3 did not apply it
# at all, and no reader anywhere applied `effective_bug_status` first. The command
# file points at this module and states no map of its own - a second copy would be
# a second answer, and the first thing to disagree would be somebody's board.
#
# THESE NAME AGILE STATES. A Scrum process knows no `Active` on a Product Backlog
# Item, so a Scrum board must set `meta.ado.stateMap`; `/audit:sync connect` says
# so from the process it detected, and every row below carries which of the two
# answered it.
TASK_STATE_DEFAULTS = {"pending": "New", "in_progress": "Active",
                       "blocked": "Active", "done": "Closed",
                       "cancelled": "Removed"}

BUG_STATE_DEFAULTS = {"open": "New", "triaged": "Active", "in_progress": "Active",
                      "fixed": "Resolved", "wontfix": "Closed"}

# A phase's defaults ARE the task defaults, spelled by reference rather than
# copied: written out twice they would be two tables that agree until one of them
# is edited. The vocabularies still differ on the BOARD side, which is what
# `stateMap.phase` is for.
DEFAULT_STATE_MAP = {"task": TASK_STATE_DEFAULTS, "bug": BUG_STATE_DEFAULTS,
                     "phase": TASK_STATE_DEFAULTS}

# What happened to one payload entry. Distinct words rather than a boolean, because
# "no manifest link claims this id" and "this transition never moves a card" are
# different answers that would both be `False`.
STAMPED = "stamped"
NEVER = "never moves"
NO_STATE = "no state"
NO_LINK = "no link"
SKIPPED = "skipped"
# Two manifest items linking to ONE work item, disagreeing about its state. Nothing
# validates that a work-item id is claimed once - `check_ado_meta` grades the SHAPE
# of a link, never the uniqueness of its target - so the payload really can be
# handed an id that two items answer for. Picking either silently would push one
# item's status onto a card the other one also owns.
CONTESTED = "contested"


# --- the manifest side ------------------------------------------------------------
def state_map_of(manifest):
    """`meta.ado.stateMap` as a dict, or `{}`. Tolerant on the way down.

    A wrong-typed `meta`, `ado` or `stateMap` is `_manifest_ado.check_ado_meta`'s
    finding to report and `validate-manifest.py`'s to print; refusing here would
    make a read-only lens the loudest thing about a defect it does not own.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    block = ado.get("stateMap") if isinstance(ado, dict) else None
    return block if isinstance(block, dict) else {}


def mapped_state(kind, status, configured):
    """The ADO state this status means, and where that answer came from.

    `{"state", "never", "basis"}`. `state` is None twice over and the two are told
    apart by `never`: a `null` in `meta.ado.stateMap` is a DECISION that this
    transition leaves the card alone, and a status nothing maps is a gap. Reporting
    both as "no state" would make a configured choice look like a defect.
    """
    if not status:
        return {"state": None, "never": False,
                "basis": "the item carries no status - nothing to translate"}
    block = configured.get(kind) if isinstance(configured, dict) else None
    block = block if isinstance(block, dict) else {}
    if status in block:
        value = block[status]
        if value is None:
            return {"state": None, "never": True,
                    "basis": "meta.ado.stateMap.%s.%s is null - this transition "
                             "never moves the card" % (kind, status)}
        if isinstance(value, str) and value.strip():
            return {"state": value, "never": False,
                    "basis": "meta.ado.stateMap.%s.%s" % (kind, status)}
        return {"state": None, "never": False,
                "basis": "meta.ado.stateMap.%s.%s is %r, which is not a state "
                         "name (validate-manifest.py refuses it)"
                         % (kind, status, value)}
    default = DEFAULT_STATE_MAP.get(kind, {}).get(status)
    if default:
        return {"state": default, "never": False,
                "basis": "built-in default %s.%s (an Agile state - a Scrum board "
                         "needs meta.ado.stateMap)" % (kind, status)}
    return {"state": None, "never": False,
            "basis": "nothing maps %s status %r - not meta.ado.stateMap, not the "
                     "built-in defaults" % (kind, status)}


def status_by_key(manifest):
    """`{(kind, id): (status, basis)}` for every phase, task and bug.

    The BUG rows go through `_manifest_io.effective_bug_status`, and the basis says
    when that derivation moved the answer: a bug whose fix task is done reads
    `fixed` here while `bug.status` still says `open`, and pushing the stored value
    would move a Resolved card back to New.

    Keyed by (kind, id) rather than by id alone because a phase and a bug may
    legitimately share a numeral in their ids, and `link_inventory` already knows
    which kind each link belongs to.
    """
    out = {}
    if not isinstance(manifest, dict):
        return out
    task_by_id = _mio.tasks_by_id(manifest)
    for phase in (manifest.get("phases") or []):
        if isinstance(phase, dict):
            out[("phase", phase.get("id"))] = (phase.get("status"),
                                               "phase.status")
    for _phase, task in _mio.iter_tasks(manifest):
        out[("task", task.get("id"))] = (task.get("status"), "task.status")
    for bug in (manifest.get("bugs") or []):
        if not isinstance(bug, dict):
            continue
        effective = _mio.effective_bug_status(bug, task_by_id)
        basis = "bug.status"
        if effective != bug.get("status"):
            basis = ("derived: bug.status is %r and fix task %s is done"
                     % (bug.get("status"), bug.get("taskId")))
        out[("bug", bug.get("id"))] = (effective, basis)
    return out


def kind_totals(manifest):
    """`{kind: how many of them the manifest holds}` - linked or not.

    The denominator of the connector line. Phases are counted off
    `manifest["phases"]` and not off `iter_tasks`, which yields nothing at all for
    a phase carrying no tasks.
    """
    if not isinstance(manifest, dict):
        return {kind: 0 for kind in KINDS}
    return {"phase": len([p for p in (manifest.get("phases") or [])
                          if isinstance(p, dict)]),
            "task": len([1 for _p, _t in _mio.iter_tasks(manifest)]),
            "bug": len([b for b in (manifest.get("bugs") or [])
                        if isinstance(b, dict)])}


# --- the third class: what the plan says does not belong on a board ---------------
def _linked_keys(rows):
    """`{(kind, id)}` for every item `link_inventory` found a work item on.

    Keyed by (kind, id) rather than by id alone for `status_by_key`'s reason: a
    phase and a bug may legitimately share a numeral in their ids.
    """
    return set([(row["kind"], row["id"]) for row in rows])


def untracked_by_kind(plan_rows, linked_keys):
    """`{kind: how many items the plan keeps off the board and no card claims}`.

    ITS OWN CLASS, never a smaller kind of `unlinked`. An item whose plan says
    it does not belong on a shared board has no link and never will, so folding
    it into `unlinked` grows one permanent false-positive row per such item -
    and a lens carrying permanent rows stops being read, which costs it the real
    drift it exists for.

    A LINK BEATS A DECLARATION HERE, and that is forced rather than preferred:
    `link_inventory` is the authority on what `linked` means on this surface, so
    an item declared off the board while a work item still carries its id is
    counted LINKED - the card exists whatever the plan now says. Counting it in
    both classes would make the three overshoot the total, and a split a reader
    cannot add up is a split they stop checking. The leftover is not lost:
    `untracked_but_linked` is what it becomes, printed on its own line.

    A BUG IS NEVER IN HERE. The declaration is a property of a PHASE and answers
    about no bug at all, so every bug row comes back unanswered - and unanswered
    is not untracked.

    NOR IS AN UNANSWERED ROW, which is the direction that matters: this asks
    `is_untracked`, never `not is_tracked()`. Being counted untracked is a
    licence to stop reporting a gap, and a row nothing had a basis to answer has
    not earned one.

    `_ado_tracked` is where the rules and the task inheritance live. Nothing
    here re-reads the key, because a second reading would be the second policy
    whose disagreement this whole feature exists to end.
    """
    out = {kind: 0 for kind in KINDS}
    for row in (plan_rows or []):
        kind = row.get("kind")
        if kind not in out or not _tracked.is_untracked(row):
            continue
        if (kind, row.get("id")) in linked_keys:
            continue
        out[kind] += 1
    return out


def untracked_but_linked(plan_rows, linked_keys):
    """`[{kind, id, basis}]` - declared off the board, still carrying a card.

    The one item the per-kind split cannot show, because a link beats a
    declaration there. It is a leftover somebody has to unpick by hand: the plan
    says the work does not belong on the board and a work item for it is sitting
    on one anyway, so nothing will push it again and nothing will take it down.
    Named rather than counted alone, for `SHARED`'s reason one question over.
    """
    return [{"kind": row.get("kind"), "id": row.get("id"),
             "basis": row.get("basis")}
            for row in (plan_rows or [])
            if _tracked.is_untracked(row)
            and (row.get("kind"), row.get("id")) in linked_keys]


def unanswered_items(plan_rows):
    """`[{kind, id, basis}]` for every PHASE or TASK nothing could answer for.

    WHERE THE THIRD VALUE GOES, said out loud rather than folded in. The
    declaration is three-valued: on the board, deliberately off it, and `no
    basis to answer` - a key that is not a boolean, or a sharded index handed
    over un-assembled. An item in that third state is counted UNLINKED above and
    never untracked, because untracked is a licence to stop reporting a gap and
    nothing here earned one; it is listed here so that choice is visible instead
    of silent, which is what separates a decision from a default.

    BUGS ARE LEFT OUT, for `_ado_tracked.counts`' reason: every bug is
    unanswered by construction, so folding them in would make this a number that
    can never reach zero and would report the ordinary state of every bug as a
    gap in the plan.
    """
    return [{"kind": row.get("kind"), "id": row.get("id"),
             "basis": row.get("basis")}
            for row in (plan_rows or [])
            if row.get("kind") != "bug" and row.get("tracked") is None]


def manifest_side(manifest):
    """Every link, its status, its target state, and the counts over the lot.

    `link_inventory` is the authority on WHICH items are linked - the same walk
    `fetch-ado-items.py` asks which ids to fetch, so the two can never disagree
    about what "linked" means. This function adds the STATUS half, which that walk
    deliberately does not carry.

    THE PER-KIND SPLIT IS A PARTITION OF `total`: linked, unlinked, untracked,
    and `unlinked` is what is left after the other two rather than a class of its
    own. It was `total - linked` alone, which is why every item a plan keeps off
    the board read as a gap for ever. `_ado_tracked` supplies the third class.

    THE MANIFEST MUST ARRIVE ASSEMBLED. `main` loads it through
    `_manifest_io.load_manifest` for the links, and the declaration needs the
    same read for a stronger reason: on the sharded layout both the key and the
    tasks live in the shard BODY, so a raw read reports a whole plan tracked by
    default with no task rows at all.
    """
    configured = state_map_of(manifest)
    status = status_by_key(manifest)
    rows = []
    for link in _drift.link_inventory(manifest):
        key = (link["kind"], link["id"])
        stored, basis = status.get(key, (None, "no manifest item carries this id"))
        row = {"kind": link["kind"], "id": link["id"], "adoId": link["adoId"],
               "status": stored, "statusBasis": basis}
        row.update(mapped_state(link["kind"], stored, configured))
        rows.append(row)
    totals = kind_totals(manifest)
    linked = {kind: len([r for r in rows if r["kind"] == kind]) for kind in KINDS}
    keys = _linked_keys(rows)
    plan_rows = _tracked.inventory(manifest)["rows"]
    untracked = untracked_by_kind(plan_rows, keys)
    still_linked = untracked_but_linked(plan_rows, keys)
    unanswered = unanswered_items(plan_rows)
    shared = claims_shared_by_several(rows)
    return {"rows": rows,
            "kinds": {kind: {"linked": linked[kind],
                             "unlinked": (totals[kind] - linked[kind]
                                          - untracked[kind]),
                             "untracked": untracked[kind],
                             "total": totals[kind]} for kind in KINDS},
            "counts": {"links": len(rows),
                       "withState": len([r for r in rows
                                         if r["state"] is not None]),
                       "never": len([r for r in rows if r["never"]]),
                       "noState": len([r for r in rows if r["state"] is None
                                       and not r["never"]]),
                       "derived": len([r for r in rows if _is_derived(r)]),
                       "untracked": sum(untracked.values()),
                       "untrackedLinked": len(still_linked),
                       "unanswered": len(unanswered),
                       "sharedTargets": len(shared)},
            "untrackedLinked": still_linked,
            "unanswered": unanswered,
            "sharedTargets": shared,
            "stateMapKinds": sorted(configured)}


def claims_by_ado(rows):
    """`{adoId: [row, ...]}` - every manifest item that claims that work item.

    A LIST and not the first row. Nothing anywhere refuses two manifest items
    pointing at one card: `check_ado_meta` grades the shape of a link and never
    the uniqueness of its target, and an import that adopts a card already linked
    by hand produces exactly that. Reducing to one here would silently decide
    whose status the card gets.
    """
    out = {}
    for row in rows:
        out.setdefault(row["adoId"], []).append(row)
    return out


def claims_shared_by_several(rows):
    """`[{adoId, claimants, agree}]` for every card more than one item claims.

    Sorted by work-item id so a regenerated report is the same report. `agree`
    is what decides whether the stamp can still answer: two items that mean the
    same state give one answer, and two that do not give none.
    """
    out = []
    for ado_id, claimants in claims_by_ado(rows).items():
        if len(claimants) < 2:
            continue
        answers = set([(r["state"], bool(r["never"])) for r in claimants])
        out.append({"adoId": ado_id,
                    "claimants": ["%s %s" % (r["kind"], r["id"])
                                  for r in claimants],
                    "agree": len(answers) == 1})
    return sorted(out, key=lambda entry: entry["adoId"])


def _is_derived(row):
    """True when this row's status was not read off the item's own field.

    Only bugs can be, today. Named as a predicate rather than compared inline
    because the REPORT owes the reader that distinction: a bug whose status reads
    `fixed` while the file says `open` looks like a table with a typo in it until
    the derivation is stated.
    """
    return row.get("statusBasis") != "%s.status" % (row.get("kind"),)


# --- stamping the fetched payload -------------------------------------------------
def stamp(side, items):
    """`items` with `mapped` filled in, plus one outcome per entry.

    A NEW list of NEW dicts: the caller's payload is the file `fetch-ado-items.py`
    wrote and stays readable as that. An entry this function cannot map is passed
    through UNCHANGED and named - dropping it would hand `explain-ado-drift.py` a
    shorter payload, and a table missing a row reads as a board with fewer cards.
    """
    by_ado = claims_by_ado(side.get("rows") or [])

    out, entries = [], []
    for item in (items or []):
        if not isinstance(item, dict):
            out.append(item)
            entries.append({"adoId": None, "outcome": SKIPPED, "mapped": None,
                            "restamped": False, "claimants": [],
                            "why": "payload entry is not an object"})
            continue
        ado_id = item.get("id")
        # `link_inventory` yields none but real ints, so anything else can only
        # miss - and asking a dict for an unhashable key raises rather than
        # missing, which turned a malformed payload into a traceback instead of
        # the named row this command owes for every entry it cannot place.
        claimants = (by_ado.get(ado_id) or []
                     if isinstance(ado_id, int) and not isinstance(ado_id, bool)
                     else [])
        names = ["%s %s" % (r["kind"], r["id"]) for r in claimants]
        row = claimants[0] if claimants else None
        contested = len(set([(r["state"], bool(r["never"]))
                             for r in claimants])) > 1
        fresh = dict(item)
        if row is None:
            entries.append({"adoId": ado_id, "outcome": NO_LINK, "mapped": None,
                            "restamped": False, "claimants": names,
                            "why": "no manifest item links to this work item"})
        elif contested:
            # NOT stamped, and not reduced to whichever item the walk reached
            # first: two owners with two answers is no answer, and a card written
            # from one of them would be the manifest overwriting itself.
            entries.append({"adoId": ado_id, "outcome": CONTESTED,
                            "mapped": None, "restamped": False,
                            "claimants": names,
                            "why": "claimed by %s, and they do not agree on a "
                                   "state (%s) - fix the duplicate link rather "
                                   "than letting this command pick"
                                   % (", ".join(names),
                                      ", ".join([str(r["state"])
                                                 for r in claimants]))})
        elif row["state"] is None:
            entries.append({"adoId": ado_id,
                            "outcome": NEVER if row["never"] else NO_STATE,
                            "mapped": None, "restamped": False,
                            "claimants": names,
                            "why": row["basis"], "kind": row["kind"],
                            "id": row["id"]})
        else:
            was = item.get("mapped")
            fresh["mapped"] = row["state"]
            entries.append({"adoId": ado_id, "outcome": STAMPED,
                            "mapped": row["state"],
                            "restamped": was is not None and was != row["state"],
                            "claimants": names,
                            "why": row["basis"], "kind": row["kind"],
                            "id": row["id"]})
        out.append(fresh)

    counts = {"entries": len(entries),
              "restamped": len([e for e in entries if e["restamped"]]),
              # Counted even where the answer still came out: agreeing on a state
              # does not make one card belonging to two manifest items correct,
              # and this is the only surface that walks both sides at once.
              "shared": len([e for e in entries if len(e["claimants"]) > 1])}
    for outcome in (STAMPED, NEVER, NO_STATE, NO_LINK, CONTESTED, SKIPPED):
        counts[outcome] = len([e for e in entries if e["outcome"] == outcome])
    return {"items": out, "entries": entries, "counts": counts}


# --- what it prints ---------------------------------------------------------------
HEAD = ("kind", "manifest", "ado", "status", "state", "basis")


def table(rows):
    """The rows as aligned lines, header first. Empty in, empty out."""
    if not rows:
        return []
    body = [(r.get("kind") or "?", str(r.get("id") or "?"),
             "#%s" % (r.get("adoId"),), str(r.get("status") or "-"),
             r.get("state") or ("never" if r.get("never") else "-"),
             r.get("basis") or "?") for r in rows]
    widths = [max(len(HEAD[i]), max(len(line[i]) for line in body))
              for i in range(len(HEAD))]
    fmt = "  ".join("%-" + str(w) + "s" for w in widths)
    return [(fmt % HEAD).rstrip(),
            (fmt % tuple("-" * w for w in widths)).rstrip()] \
        + [(fmt % line).rstrip() for line in body]


def inventory_lines(side, manifest_path, layout):
    """The connector line's own numbers, with the read that produced them named.

    The layout is printed because it IS the basis: the same manifest read raw
    answers a different, smaller number, and a reader who cannot see which read
    happened cannot tell the two apart.
    """
    out = ["manifest: %s (%s layout, read assembled through "
           "_manifest_io.load_manifest)" % (manifest_path, layout)]
    # The third figure prints for every kind INCLUDING `bug`, where it is always
    # zero: the declaration is a property of a phase and answers about no bug, so
    # a bug line missing the column would read as a kind nobody asked about
    # rather than as a kind the question does not cover.
    for kind in KINDS:
        counts = side["kinds"][kind]
        out.append("  %-5s %d linked, %d unlinked, %d deliberately untracked "
                   "(%d in the manifest)"
                   % (kind, counts["linked"], counts["unlinked"],
                      counts["untracked"], counts["total"]))
    # Printed even when they are zero, every one of them. A count that appears only
    # when it is interesting cannot be told apart from a count nobody computed, and
    # `withState` reaching zero is the whole shape this command exists to expose.
    out.append("%d link(s): %d with a target state, %d never moved by "
               "configuration, %d with no state at all"
               % (side["counts"]["links"], side["counts"]["withState"],
                  side["counts"]["never"], side["counts"]["noState"]))
    # Also at zero. Nothing refuses two manifest items pointing at one card, so
    # this is the only place it is ever counted - and a reader who cannot see the
    # number reads a table with two rows carrying one work-item id as a typo.
    out.append("%d work item(s) claimed by more than one manifest item"
               % (side["counts"]["sharedTargets"],))
    for shared in side["sharedTargets"]:
        out.append("  SHARED: #%s claimed by %s - %s"
                   % (shared["adoId"], ", ".join(shared["claimants"]),
                      "they agree on a state" if shared["agree"] else
                      "and they DISAGREE, so nothing can be stamped for it"))
    # Also at zero, and for the reason above: a DERIVED status is one the manifest
    # file does not carry in the field being reported, so a reader comparing this
    # table against the JSON has to be told which rows those are - or the honest
    # answer looks like a bug in the table.
    out.append("%d status(es) derived rather than read off the item's own field"
               % (side["counts"]["derived"],))
    for row in side["rows"]:
        if _is_derived(row):
            out.append("  DERIVED: %s %s reads %r - %s"
                       % (row["kind"], row["id"], row["status"],
                          row["statusBasis"]))
    # Also at zero. The declaration is three-valued and the third value is "no
    # basis to answer" - a key that is not a boolean, a shard stub nobody
    # assembled. Those items are counted UNLINKED above and never untracked,
    # because untracked is a licence to stop reporting a gap; printing the figure
    # is what keeps that choice from being a silent fold, and a reader who cannot
    # see it reads every unlinked row as drift.
    out.append("%d plan item(s) whose %s could not be answered - counted as "
               "unlinked, never as untracked"
               % (side["counts"]["unanswered"], _tracked.FIELD))
    for item in side["unanswered"]:
        out.append("  NOT ANSWERED: %s %s - %s"
                   % (item["kind"], item["id"], item["basis"]))
    # And at zero as well, for the reason above one question over: an item its
    # plan keeps off the board while a card for it still exists is counted
    # LINKED, because the card is there whatever the plan now says. That is the
    # one item the per-kind line cannot show, and it is the one somebody has to
    # unlink by hand - nothing will push it again and nothing will take it down.
    out.append("%d item(s) declared off the board that still carry a link"
               % (side["counts"]["untrackedLinked"],))
    for item in side["untrackedLinked"]:
        out.append("  STILL LINKED: %s %s - %s"
                   % (item["kind"], item["id"], item["basis"]))
    if not side["stateMapKinds"]:
        out.append("meta.ado.stateMap: not configured - every state above is a "
                   "built-in Agile default")
    else:
        out.append("meta.ado.stateMap configures: %s"
                   % (", ".join(side["stateMapKinds"]),))
    return out


def stamp_lines(result, out_path):
    """What was written, and what could not be - by id, never by count alone."""
    counts = result["counts"]
    out = ["%d payload entry(s): %d stamped, %d never moved by configuration, "
           "%d with no state, %d matching no manifest link, %d contested by two "
           "manifest items, %d unreadable"
           % (counts["entries"], counts[STAMPED], counts[NEVER],
              counts[NO_STATE], counts[NO_LINK], counts[CONTESTED],
              counts[SKIPPED])]
    if counts["restamped"]:
        out.append("%d entry(s) already carried a DIFFERENT mapped state and were "
                   "restamped from the manifest" % (counts["restamped"],))
    for entry in result["entries"]:
        if entry["outcome"] == STAMPED:
            # A card two manifest items agree about IS stamped, and is still a
            # duplicate link somebody has to unpick - so it is named here rather
            # than left to look like an ordinary row.
            if len(entry["claimants"]) > 1:
                out.append("ALSO CLAIMED: #%s stamped %s, but %s both link to it"
                           % (entry["adoId"], entry["mapped"],
                              " and ".join(entry["claimants"])))
            continue
        out.append("NOT STAMPED: #%s (%s) - %s"
                   % (entry["adoId"], entry["outcome"], entry["why"]))
    out.append("wrote %s - hand THAT file to explain-ado-drift.py --items"
               % (out_path,))
    return out


# --- cli --------------------------------------------------------------------------
def _flag(argv, name):
    """The value after `name`, or None. A following flag counts as absent."""
    if name not in argv:
        return None
    idx = argv.index(name)
    value = argv[idx + 1] if len(argv) > idx + 1 else None
    if not value or value.startswith("--"):
        return None
    return value


def _read_items(path):
    """(payload, error). Reads `-` from stdin, like the sibling doors do."""
    try:
        if path == "-":
            return (json.load(sys.stdin), None)
        with open(path, "r", encoding="utf-8") as fh:
            return (json.load(fh), None)
    except Exception as exc:
        return (None, "cannot read/parse items %s: %s" % (path, exc))


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]
    items_path = _flag(argv, "--items")
    out_path = _flag(argv, "--out")
    if ("--items" in argv) != bool(items_path):
        sys.stderr.write(USAGE)
        return 2
    # `--items` without `--out` is refused rather than treated as a preview: the
    # preview is this command with no `--items` at all, and a run that reported a
    # translation while writing no file is one forgotten flag away from the
    # UNSTAMPED payload reaching the drift door - the defect this command ends.
    if items_path and not out_path:
        sys.stderr.write("ERROR: --items needs --out <file.json> - the stamped "
                         "payload is the point, and a run that wrote nothing "
                         "leaves the unstamped one to be passed on\n")
        return 2
    if out_path and not items_path:
        sys.stderr.write(USAGE)
        return 2

    # THE LOADER, NEVER A BARE `json.load`. On the sharded layout the file at
    # `manifest_path` is an index whose phases are stubs, so a raw read finds the
    # bugs' links and none of the phases' or tasks' - and reports the difference as
    # "unlinked", which is a confident wrong answer about somebody's board.
    try:
        manifest = _mio.load_manifest(manifest_path)
        layout = _mio.layout_of(_mio.read_json(manifest_path))
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse manifest %s: %s\n"
                         % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (manifest_path,))
        return 2

    side = manifest_side(manifest)

    if not items_path:
        if "--json" in argv:
            print(json.dumps(side, indent=2, sort_keys=True))
        else:
            for line in inventory_lines(side, manifest_path, layout):
                print(line)
            for line in table(side["rows"]):
                print(line)
        return 0

    items, err = _read_items(items_path)
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2
    # Shape before substance, and exit 2 rather than an empty answer: a list is the
    # documented payload, and stamping nothing onto something we could not read
    # would send the drift door a file that looks answered.
    if not isinstance(items, list):
        sys.stderr.write("ERROR: --items wants a JSON list of {id, fields}, "
                         "got %s\n" % (type(items).__name__,))
        return 2

    result = stamp(side, items)
    try:
        _mio.atomic_write_json(out_path, result["items"])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot write %s: %s\n" % (out_path, exc))
        return 2

    if "--json" in argv:
        print(json.dumps({"side": side, "stamp": result}, indent=2,
                         sort_keys=True))
    else:
        for line in inventory_lines(side, manifest_path, layout):
            print(line)
        for line in stamp_lines(result, out_path):
            print(line)

    # An EMPTY payload is not this failure: nothing was asked about, and the counts
    # above say so. A payload with entries in it and not one state to compare is,
    # because every reading downstream then has no basis - including the overwrite
    # count the push confirm gate reads, which would be zero for that reason alone.
    if items and not result["counts"][STAMPED]:
        sys.stderr.write("ERROR: not one of the %d payload entry(s) could be "
                         "given a state, so nothing downstream can compare one - "
                         "the drift table would read `state not compared` for "
                         "every row and `0 would overwrite` for the board\n"
                         % (len(items),))
        return 1
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("read-ado-links.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_read_ado_links.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
