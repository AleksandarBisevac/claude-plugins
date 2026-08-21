#!/usr/bin/env python3
"""
Who moved a linked work item last, and whether pushing would overwrite them.

`/audit:sync status` used to offer a difference two readings: our side is right
(run `push`) or ADO is right (edit the manifest). On a board with more than one
legitimate source of work items - several services, several teams, several people
creating cards - the commonest reading is the THIRD one: somebody else moved this
card after we last touched it, and neither side is wrong. Silence about that is
what turns a drift table into an invitation to overwrite a colleague.

THE INVARIANT THIS RESTS ON. A push writes ADO first and the manifest's
`lastSyncedAt` second, so for a write of OUR OWN it always holds that
`System.ChangedDate <= lastSyncedAt`. That is why "after us" needs no identity at
all: the question is not WHO wrote (the plugin does not know its own ADO identity)
but WHETHER anyone wrote after us. `System.ChangedBy` rides along as information
for the reader, never as an input to the comparison.

WHY A TOLERANCE. `lastSyncedAt` comes from the local clock, `ChangedDate` from
ADO's server clock. A few seconds of skew is ordinary, and without a margin our
own write would read as somebody else's. `DEFAULT_TOLERANCE_S` is that margin. Its
honest limit: skew LARGER than the margin degrades the answer to `unknown` in one
direction and to `external_change` in the other - so the margin is generous rather
than tight, and a caller may raise it.

THE SHAPES ARE MEASURED, NOT ASSUMED (`verifying-external-behavior`). Probed live
against `az boards work-item show` on the lab board: `System.ChangedDate` is
`'2026-08-21T06:30:20.377Z'` (fractional seconds, trailing Z - which is why
`_usage_core.parse_ts` is reused rather than a fourth ISO parser written), and
`System.ChangedBy` is an OBJECT carrying `displayName` and `uniqueName`, not a
string. The MCP transport (`wit_work_item`) could NOT be probed from here - that
server authenticates as a different identity and is not authorized on the lab
board - so `changed_by` accepts a plain string as well, and says which shape it
read. An unverified second transport is a reason to tolerate both and report
which, not a reason to assume they match.

WHAT IS DELIBERATELY NOT HERE. The manifest-status -> ADO-state map lives in
`commands/sync.md` and nowhere else; this module does not reproduce it, because a
second copy is a second answer. `mapped` is therefore an INPUT: pass it and the
row can say whether the states agree, omit it and the row says the comparison was
not supplied - never that the item is in sync.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_drift.py`.
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

import _manifest_io as _mio  # noqa: E402  (the one task walk)
import _manifest_vocab as _vocab  # noqa: E402  (the manifest's words: ado.origin)
import _usage_core as _uc  # noqa: E402  (parse_ts: the tree's ISO parser)

# Seconds of clock skew tolerated between the local `date -u` that wrote
# `lastSyncedAt` and the ADO server clock that stamped `ChangedDate`. Generous on
# purpose: the cost of being too tight is calling our own write somebody else's,
# which is the exact false claim this module exists to prevent.
DEFAULT_TOLERANCE_S = 120

# The time classes. `unknown` is a first-class answer, not a fallback: a link that
# was never synced has no basis for either verdict, and inventing one is the defect.
LOCAL_AHEAD = "local_ahead"
EXTERNAL_CHANGE = "external_change"
UNKNOWN = "unknown"
CLASSES = (LOCAL_AHEAD, EXTERNAL_CHANGE, UNKNOWN)

# What a link's `origin` may say - ALIASES, not copies. The vocabulary belongs to
# `_manifest_vocab` (L1), where the validator that refuses a misspelled one reads
# it; a second tuple here would be a second answer, and the first time they
# disagreed the manifest would be the thing that told us. Absent stays a third
# state that is deliberately not in the tuple: it means unrecorded, and it is said
# out loud rather than defaulted.
ORIGIN_CREATED = _vocab.ADO_ORIGIN_CREATED
ORIGIN_IMPORTED = _vocab.ADO_ORIGIN_IMPORTED
ORIGINS = _vocab.ADO_ORIGIN

CHANGED_BY_FIELD = "System.ChangedBy"
CHANGED_AT_FIELD = "System.ChangedDate"
STATE_FIELD = "System.State"


# --- reading the ADO side -------------------------------------------------------

def changed_by(fields):
    """Who last wrote the item, and which shape that answer was read from.

    Measured: `az` returns an identity OBJECT (`displayName`, `uniqueName`). The
    MCP transport is unverified here, so a bare string is accepted too. The basis
    travels with the name because "we read a string where an object was expected"
    is the kind of thing that shows up as a blank column months later.
    """
    val = (fields or {}).get(CHANGED_BY_FIELD)
    if isinstance(val, dict):
        name = val.get("displayName") or val.get("uniqueName")
        if name:
            return {"name": str(name),
                    "basis": ("%s.displayName" % CHANGED_BY_FIELD
                              if val.get("displayName")
                              else "%s.uniqueName" % CHANGED_BY_FIELD)}
        return {"name": None,
                "basis": "%s is an object carrying neither displayName nor "
                         "uniqueName" % CHANGED_BY_FIELD}
    if isinstance(val, str) and val.strip():
        return {"name": val.strip(),
                "basis": "%s as a plain string (the shape the MCP transport was "
                         "not probed for)" % CHANGED_BY_FIELD}
    return {"name": None, "basis": "%s absent" % CHANGED_BY_FIELD}


def changed_at(fields):
    """The item's last-change stamp as ADO sent it, or None."""
    val = (fields or {}).get(CHANGED_AT_FIELD)
    return val if isinstance(val, str) and val.strip() else None


def ado_state(fields):
    """The item's state as ADO sent it, or None."""
    val = (fields or {}).get(STATE_FIELD)
    return val if isinstance(val, str) and val.strip() else None


# --- the link's own answers -----------------------------------------------------

def origin_of(link):
    """Was this card born here, adopted, or is that unrecorded?

    A link written before `origin` existed answers `unknown`, and the basis says
    so rather than letting the reader assume the plugin created the item. The
    provenance TAG cannot answer this: `meta.ado.tag` is merged onto every item a
    push touches, so it proves the plugin wrote to a card, not that it made one.
    """
    if not isinstance(link, dict) or not link:
        return {"origin": UNKNOWN, "basis": "no link"}
    val = link.get("origin")
    if val in ORIGINS:
        return {"origin": val, "basis": "ado.origin"}
    if val is None:
        return {"origin": UNKNOWN,
                "basis": "ado.origin absent - link written before the field "
                         "existed, or by hand"}
    return {"origin": UNKNOWN,
            "basis": "ado.origin %r is not one of %s"
                     % (val, ", ".join(ORIGINS))}


def classify(link, fields, mapped=None, tolerance=DEFAULT_TOLERANCE_S):
    """Did anyone write this item after our last sync - and do the states agree?

    Two orthogonal answers in one row, deliberately not collapsed into one enum:
    `class` is about TIME (who wrote last) and `drift` is about STATE (whether the
    mapped status matches). Collapsing them would make "in sync" hide the fact
    that somebody else moved the card into the state we happened to want.

    `mapped` is the manifest status already translated through `meta.ado.stateMap`
    by the caller - `sync.md` owns that table. Omitted => `drift` is None, and the
    row says the comparison was not supplied.
    """
    link = link if isinstance(link, dict) else {}
    synced_raw = link.get("lastSyncedAt")
    synced = _uc.parse_ts(synced_raw)
    changed_raw = changed_at(fields)
    changed = _uc.parse_ts(changed_raw)
    state = ado_state(fields)
    who = changed_by(fields)

    if changed is None:
        cls = UNKNOWN
        basis = ("%s %s" % (CHANGED_AT_FIELD,
                            "absent" if changed_raw is None
                            else "unparseable (%r)" % (changed_raw,)))
    elif synced is None:
        cls = UNKNOWN
        basis = ("ado.lastSyncedAt %s - nothing to compare %s against"
                 % ("absent" if synced_raw is None
                    else "unparseable (%r)" % (synced_raw,), CHANGED_AT_FIELD))
    elif changed > synced + tolerance:
        cls = EXTERNAL_CHANGE
        basis = ("%s %s is after ado.lastSyncedAt %s (tolerance %ds)"
                 % (CHANGED_AT_FIELD, changed_raw, synced_raw, tolerance))
    else:
        cls = LOCAL_AHEAD
        basis = ("%s %s is not after ado.lastSyncedAt %s (tolerance %ds)"
                 % (CHANGED_AT_FIELD, changed_raw, synced_raw, tolerance))

    drift = None if mapped is None else (str(mapped) != str(state))
    return {"class": cls, "basis": basis, "drift": drift,
            "adoState": state, "mapped": None if mapped is None else str(mapped),
            "changedBy": who["name"], "changedByBasis": who["basis"],
            "changedAt": changed_raw, "origin": origin_of(link)}


# --- what the row says out loud -------------------------------------------------

def verdict(row):
    """The one phrase a table cell carries. Never a verdict without its basis."""
    cls = (row or {}).get("class")
    drift = (row or {}).get("drift")
    who = (row or {}).get("changedBy")
    when = (row or {}).get("changedAt")
    if cls == UNKNOWN:
        return "unknown - never synced or unstamped"
    if drift is None:
        return "state not compared (no mapped state supplied)"
    if not drift:
        if cls == EXTERNAL_CHANGE:
            return ("in sync, but last written by %s%s - not by us"
                    % (who or "someone else", (" at %s" % when) if when else ""))
        return "in sync"
    if cls == EXTERNAL_CHANGE:
        return ("external%s%s - push would overwrite it"
                % ((" (%s" % who) if who else " (unnamed writer",
                   (", %s)" % when) if when else ")"))
    return "local ahead - push is the fix"


def advice(row):
    """The action to suggest, or None when there is no basis to suggest one.

    `unknown` gets NO suggestion on purpose. The house rule is that a claim
    carries the basis that makes it true; a suggestion built on a missing
    timestamp is the same defect wearing a helpful voice.
    """
    cls = (row or {}).get("class")
    drift = (row or {}).get("drift")
    if drift is None or cls == UNKNOWN:
        return None
    if not drift:
        return None
    if cls == EXTERNAL_CHANGE:
        return ("reconcile deliberately: `push` overwrites the external change, "
                "editing the manifest keeps it")
    return "push"


# --- the manifest side ----------------------------------------------------------

def link_inventory(manifest):
    """Every linked item in the manifest, as `{kind, id, link}`, phases first.

    One walk shared by the door and by `/audit:doctor`'s `ado links` row, which
    used to do its own. `ado.id` must be an int and not a bool - `True` would
    otherwise pass for a work-item id (the F15 shape, held by the validator).
    """
    out = []
    for phase in ((manifest or {}).get("phases") or []):
        if isinstance(phase, dict):
            _collect(out, "phase", phase.get("id"), phase.get("ado"))
    for _phase, task in _mio.iter_tasks(manifest or {}):
        if isinstance(task, dict):
            _collect(out, "task", task.get("id"), task.get("ado"))
    for bug in ((manifest or {}).get("bugs") or []):
        if isinstance(bug, dict):
            _collect(out, "bug", bug.get("id"), bug.get("ado"))
    return out


def _collect(out, kind, item_id, link):
    if not isinstance(link, dict):
        return
    ado_id = link.get("id")
    if isinstance(ado_id, bool) or not isinstance(ado_id, int):
        return
    out.append({"kind": kind, "id": item_id, "adoId": ado_id, "link": link})


def origin_breakdown(inventory):
    """`{created, imported, unknown, total}` over an inventory.

    Counted rather than described, because the interesting number is `unknown`:
    it is how many links predate the field, and it shrinks only as those items are
    pushed again. A reader who cannot see it reads the other two as the whole.
    """
    out = {ORIGIN_CREATED: 0, ORIGIN_IMPORTED: 0, UNKNOWN: 0,
           "total": len(inventory or [])}
    for row in (inventory or []):
        out[origin_of(row.get("link"))["origin"]] += 1
    return out


def join(manifest, items, tolerance=DEFAULT_TOLERANCE_S):
    """Classify every fetched item against the manifest link that names it.

    `items` is what the command already pulled for its diff: a list of
    `{"id": <int>, "fields": {...}}`, optionally carrying `"mapped"` - the
    manifest status already translated by `sync.md`'s table.

    Two failure modes are reported rather than dropped: a fetched item no manifest
    link claims (`unlinked`), and a link whose item was not fetched (`unfetched`).
    Dropping either would make a short table look complete.
    """
    inventory = link_inventory(manifest)
    by_id = {}
    for row in inventory:
        by_id.setdefault(row["adoId"], row)

    rows, unlinked = [], []
    seen = set()
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        ado_id = item.get("id")
        if isinstance(ado_id, bool) or not isinstance(ado_id, int):
            unlinked.append({"adoId": ado_id,
                             "why": "fetched item has no integer id"})
            continue
        owner = by_id.get(ado_id)
        if owner is None:
            unlinked.append({"adoId": ado_id,
                             "why": "no manifest item links to this work item"})
            continue
        seen.add(ado_id)
        row = classify(owner["link"], item.get("fields"),
                       mapped=item.get("mapped"), tolerance=tolerance)
        row.update({"kind": owner["kind"], "id": owner["id"], "adoId": ado_id})
        row["verdict"] = verdict(row)
        row["advice"] = advice(row)
        rows.append(row)

    unfetched = [{"kind": r["kind"], "id": r["id"], "adoId": r["adoId"]}
                 for r in inventory if r["adoId"] not in seen]
    return {"rows": rows, "unlinked": unlinked, "unfetched": unfetched,
            "origins": origin_breakdown(inventory), "tolerance": tolerance}


def summarize(result):
    """Counts a caller can print without re-walking the rows."""
    rows = (result or {}).get("rows") or []
    return {"total": len(rows),
            "external": len([r for r in rows if r["class"] == EXTERNAL_CHANGE
                             and r["drift"]]),
            "localAhead": len([r for r in rows if r["class"] == LOCAL_AHEAD
                               and r["drift"]]),
            "unknown": len([r for r in rows if r["class"] == UNKNOWN]),
            "inSync": len([r for r in rows if r["drift"] is False]),
            "uncompared": len([r for r in rows if r["drift"] is None]),
            "unlinked": len((result or {}).get("unlinked") or []),
            "unfetched": len((result or {}).get("unfetched") or [])}


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_ado_drift.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__ado_drift.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
