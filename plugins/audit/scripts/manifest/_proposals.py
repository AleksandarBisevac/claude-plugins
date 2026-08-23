#!/usr/bin/env python3
"""
The proposal lifecycle: what materialize, drop and revive MEAN.

Split from `materialize-proposal.py` the moment a second caller appeared. That file
is now the door; this is the rule, and the split is the same one
`check-ado-item.py` has over `_ado_conventions.py` - made for a reason the layer
lint stated rather than taste: the panel's write path sits BELOW the entry points,
so a panel reaching up to a command is an edge pointing the wrong way. Both doors
import this, downward.

WHAT LIVES HERE. The refusals, the id allocation, the collision remap, the
dependency closure, the plan, `run()` - which takes the index lock, applies,
revalidates and writes - and `proposal_rows`, which is the READ side both surfaces
render. Orchestration is part of the rule: a caller that had to remember to lock,
or to refuse a write whose result would be invalid, is a second chance to get it
wrong.

THE READ SIDE IS PART OF THE RULE TOO, and it took F91 to notice. `list` was the
one verb no script produced: `commands/propose.md` specified a table and a model
rendered it from that prose, so what a user got was whatever the model recalled -
an accurate summary, and no table. Meanwhile the panel derived its own rows in
`_panel_composition`, including a second walk that answered the same question
`unresolved_refs` already answered. One derivation now, two renderings: cards in
the panel, a table on the command line.

WHAT DOES NOT. Argument parsing, printing, and asking a human anything. `plan_for`
reports what a materialization would pull in and `run()` refuses while the answer
is undecided, because a rule that stops to interview cannot be called from an HTTP
endpoint and a rule that guesses is worse than one that refuses.

This file carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_materialize_proposal.py`, beside the door's.
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

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _locks  # noqa: E402  (the index lock, already the one implementation)
import _manifest_io as _mio  # noqa: E402  (layout-aware read and write)

LOCK_NAME = "index"


# --- reading the proposal -------------------------------------------------------
def find_proposal(manifest, pid):
    """The proposal with this id, or None. Case-sensitive, like every other id."""
    for prop in (manifest.get("proposals") or []):
        if isinstance(prop, dict) and prop.get("id") == pid:
            return prop
    return None


def refusal(prop, pid):
    """Why this proposal cannot be materialized, or None when it can.

    Every branch here is one of `propose.md`'s refusals, kept in its order so the
    two cannot drift: unknown, already materialized, dropped, or legacy free-form
    with nothing to move.
    """
    if prop is None:
        return "no proposal %s in this manifest" % (pid,)
    status = prop.get("status")
    if status == "materialized":
        return ("%s is already materialized as %s - a proposal is materialized "
                "once and the record is kept as history"
                % (pid, prop.get("materializedAs") or "a phase"))
    if status == "dropped":
        return ("%s was dropped: %s. Revive it first if that was wrong"
                % (pid, (prop.get("notes") or "no reason recorded").strip()))
    payload = prop.get("payload")
    phase = payload.get("phase") if isinstance(payload, dict) else None
    if not isinstance(phase, dict) or not phase.get("id"):
        return ("%s carries no payload.phase - a legacy free-form entry has "
                "nothing to materialize; use /audit:task add or a fresh "
                "/audit:init" % (pid,))
    return None


# --- ids ------------------------------------------------------------------------
def live_ids(manifest):
    """Every phase and task id that exists as real work right now."""
    out = set()
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            out.add(ph["id"])
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                out.add(t["id"])
    return out


def parked_ids(manifest, skip=()):
    """Ids RESERVED by still-parked payloads.

    A proposed payload reserves its ids so allocation cannot mint over them, and
    `skip` is how the proposal being materialized stops reserving against itself.
    """
    out = set()
    for prop in (manifest.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        if prop.get("id") in skip:
            continue
        payload = prop.get("payload")
        phase = payload.get("phase") if isinstance(payload, dict) else None
        if not isinstance(phase, dict):
            continue
        if phase.get("id"):
            out.add(phase["id"])
        for t in (phase.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                out.add(t["id"])
    return out


def next_phase_id(taken):
    """The lowest free `P<n>`, counting live AND parked ids."""
    n = 0
    while ("P%d" % n) in taken:
        n += 1
    return "P%d" % n


def remap_payload(phase, new_pid):
    """The payload phase under a new id, with task ids and intra-payload refs moved.

    Returns (phase, mapping). Only refs that point INSIDE this payload are
    rewritten - an edge to a live phase still means that live phase, and rewriting
    it would silently repoint real work.
    """
    old_pid = phase.get("id")
    if new_pid == old_pid:
        return json.loads(json.dumps(phase)), {}
    moved = json.loads(json.dumps(phase))
    moved["id"] = new_pid
    mapping = {old_pid: new_pid}
    for t in (moved.get("tasks") or []):
        tid = t.get("id")
        if isinstance(tid, str) and tid.startswith(old_pid + "."):
            mapping[tid] = new_pid + tid[len(old_pid):]
            t["id"] = mapping[tid]
    for t in (moved.get("tasks") or []):
        for key in ("blockedBy", "dependsOn"):
            refs = t.get(key)
            if isinstance(refs, list):
                t[key] = [mapping.get(r, r) for r in refs]
    for key in ("blockedBy", "dependsOn"):
        refs = moved.get(key)
        if isinstance(refs, list):
            moved[key] = [mapping.get(r, r) for r in refs]
    return moved, mapping


# --- dependency resolution ------------------------------------------------------
def unresolved_refs(phase, manifest, skip):
    """Refs in this payload that point at nothing live.

    Returns a list of (ref, owner) where owner is the PROP id whose parked payload
    reserves that ref, or None when the ref names nothing anywhere. `propose.md`
    treats those two differently and so must this: a parked owner is a decision,
    a dangling ref is just an edge to drop.
    """
    alive = live_ids(manifest)
    owners = {}
    for prop in (manifest.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        if prop.get("id") in skip:
            continue
        payload = prop.get("payload")
        pph = payload.get("phase") if isinstance(payload, dict) else None
        if isinstance(pph, dict) and pph.get("id"):
            owners[pph["id"]] = prop.get("id")
    out = []
    seen = set()
    refs = []
    for key in ("blockedBy", "dependsOn"):
        refs += [r for r in (phase.get(key) or []) if isinstance(r, str)]
        for t in (phase.get("tasks") or []):
            if isinstance(t, dict):
                refs += [r for r in (t.get(key) or []) if isinstance(r, str)]
    own_ids = {phase.get("id")} | set(
        t.get("id") for t in (phase.get("tasks") or []) if isinstance(t, dict))
    for ref in refs:
        if ref in alive or ref in own_ids or ref in seen:
            continue
        seen.add(ref)
        out.append((ref, owners.get(ref)))
    return out


def closure(manifest, pid, _seen=None):
    """`pid` and every parked proposal it depends on, dependency-first.

    The order is what makes `--all` mean anything: materializing a phase whose
    blocker is still parked would write a manifest the validator refuses, so the
    blocker goes first. Cycles stop at the first repeat rather than recursing -
    the validator reports the cycle itself, and this must not hang on one.
    """
    seen = set() if _seen is None else _seen
    if pid in seen:
        return []
    seen.add(pid)
    prop = find_proposal(manifest, pid)
    if prop is None:
        return []
    payload = prop.get("payload")
    phase = payload.get("phase") if isinstance(payload, dict) else None
    order = []
    if isinstance(phase, dict):
        for ref, owner in unresolved_refs(phase, manifest, skip=(pid,)):
            if owner and owner not in seen:
                order += closure(manifest, owner, seen)
    order.append(pid)
    return order


# --- reading them as a list -----------------------------------------------------
# The statuses that are HISTORY rather than a decision still waiting to be taken.
# Named rather than spelled inline because the default list filter is defined
# against it: what `list` hides is history, not "everything that is not the word
# proposed". A hand-written entry carrying something outside the vocabulary (an
# older /audit:init wrote what it liked) is neither, and hiding it by default
# would make the one surface that reads proposals in full the surface that cannot
# see it.
HISTORY_STATUS = ("materialized", "dropped")


def proposal_rows(manifest):
    """`proposals[]` as a reader sees it, whichever surface is asking.

    The panel's Proposals tab paints these as cards and `/audit:propose list`
    prints them as a table. It lived in `_panel_composition` while the panel was
    the only surface that HAD a list - the command was specified in prose and
    rendered by a model - and it computed `waitsOn` with a walk of its own beside
    `unresolved_refs`, which is the same question asked twice.

    The payload travels WHOLE (phase title, task ids, titles, risk) so the tab can
    show what materializing would add without a second request, and `dropped`
    carries its reason - an archive nobody can read is a tombstone.

    These rows are the panel's OWN state key rather than a corner of its
    composition view: that view is the plan EDITOR, and a parked phase is not part
    of the plan yet. Mixing the two is exactly the confusion F-P-32 was reported
    about, and it is the same reason the rows live here rather than beside the
    phase and task rows.
    """
    out = []
    for prop in (manifest.get("proposals") or []):
        if not isinstance(prop, dict):
            continue
        payload = prop.get("payload")
        phase = payload.get("phase") if isinstance(payload, dict) else None
        tasks = [t for t in ((phase or {}).get("tasks") or [])
                 if isinstance(t, dict)]
        out.append({
            "id": prop.get("id"),
            "name": prop.get("name"),
            "status": prop.get("status") or "proposed",
            "scope": prop.get("scope"),
            "benefit": prop.get("benefit"),
            "technicalNote": prop.get("technicalNote"),
            "openQuestions": [q for q in (prop.get("openQuestions") or [])
                              if isinstance(q, str)],
            "notes": prop.get("notes"),
            "droppedAt": prop.get("droppedAt"),
            "materializedAs": prop.get("materializedAs"),
            "materializedAt": prop.get("materializedAt"),
            "createdISO": prop.get("createdISO"),
            "hasPayload": isinstance(phase, dict) and bool(phase.get("id")),
            "phaseId": (phase or {}).get("id"),
            "phaseTitle": (phase or {}).get("title"),
            "taskCount": len(tasks),
            "tasks": [{"id": t.get("id"), "title": t.get("title"),
                       "risk": t.get("risk")} for t in tasks],
            # Which ids this payload waits on that nothing live owns. Computed
            # here so the tab can warn before the confirm and the table can print
            # it, rather than the reader discovering it from a refusal after the
            # click. `unresolved_refs` is the one implementation of that question.
            "waitsOn": ([ref for ref, _owner in
                         unresolved_refs(phase, manifest,
                                         skip=(prop.get("id"),))]
                        if isinstance(phase, dict) else []),
        })
    return out


def list_view(manifest, include_all=False):
    """The rows `/audit:propose list` shows, and the basis an empty one needs.

    `hidden` and `phaseCount` are carried rather than left to the caller because
    an empty list is a result whose MEANING depends on both: nothing parked in a
    plan that has phases is a finished decision, nothing parked in a plan that has
    none is a project that never started. A renderer that had to go back to the
    manifest for that would be the second reader of it.
    """
    rows = proposal_rows(manifest)
    shown = (rows if include_all
             else [r for r in rows if r["status"] not in HISTORY_STATUS])
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    return {"rows": shown, "all": bool(include_all), "total": len(rows),
            "hidden": len(rows) - len(shown), "phaseCount": len(phases)}


# --- the plan -------------------------------------------------------------------
def plan_for(manifest, pids, policy=None):
    """What materializing these proposals would do. Pure; writes nothing.

    `policy` is None (undecided), "with-deps" or "drop-edges". Undecided is not an
    error here - the whole point is to render the decision before it is made.
    """
    steps = []
    refused = []
    taken = live_ids(manifest) | parked_ids(manifest)
    for pid in pids:
        prop = find_proposal(manifest, pid)
        why = refusal(prop, pid)
        if why:
            refused.append({"id": pid, "reason": why})
            continue
        phase = prop["payload"]["phase"]
        want = phase.get("id")
        collides = want in live_ids(manifest)
        new_pid = next_phase_id(taken) if collides else want
        taken = taken | {new_pid}
        moved, mapping = remap_payload(phase, new_pid)
        deps = unresolved_refs(phase, manifest, skip=(pid,))
        steps.append({
            "id": pid,
            "phaseId": new_pid,
            "renamedFrom": want if collides else None,
            "taskCount": len([t for t in (moved.get("tasks") or [])
                              if isinstance(t, dict)]),
            "remapped": mapping,
            "parkedDeps": [r for r, owner in deps if owner],
            "parkedDepOwners": sorted(set(owner for _r, owner in deps if owner)),
            "danglingRefs": [r for r, owner in deps if not owner],
            "files": sorted(set(
                f for t in (moved.get("tasks") or []) if isinstance(t, dict)
                for f in (t.get("files") or []) if isinstance(f, str))),
        })
    needs = sorted(set(o for s in steps for o in s["parkedDepOwners"]
                       if o not in pids))
    return {"steps": steps, "refused": refused,
            "needsDecision": bool(needs) and policy is None,
            "pulledIn": needs, "policy": policy}


# --- applying it ----------------------------------------------------------------
def apply_materialize(manifest, plan, now):
    """Write the planned phases into the manifest. Returns (manifest, report)."""
    report = []
    for step in plan["steps"]:
        prop = find_proposal(manifest, step["id"])
        phase, _map = remap_payload(prop["payload"]["phase"], step["phaseId"])
        if plan.get("policy") == "drop-edges":
            note = ("Edges dropped at materialization: %s"
                    % ", ".join(step["parkedDeps"] + step["danglingRefs"]))
            if step["parkedDeps"] or step["danglingRefs"]:
                phase["description"] = ((phase.get("description") or "").strip()
                                        + (" " if phase.get("description") else "")
                                        + note).strip()
            for key in ("blockedBy", "dependsOn"):
                drop = set(step["parkedDeps"] + step["danglingRefs"])
                if isinstance(phase.get(key), list):
                    phase[key] = [r for r in phase[key] if r not in drop]
                for t in (phase.get("tasks") or []):
                    if isinstance(t, dict) and isinstance(t.get(key), list):
                        t[key] = [r for r in t[key] if r not in drop]
        manifest.setdefault("phases", []).append(phase)
        index = manifest.setdefault("fileIndex", {})
        for t in (phase.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            for f in (t.get("files") or []):
                if isinstance(f, str):
                    ids = index.setdefault(f, [])
                    if t.get("id") and t["id"] not in ids:
                        ids.append(t["id"])
        prop["status"] = "materialized"
        prop["materializedAs"] = step["phaseId"]
        prop["materializedAt"] = now
        report.append("%s -> %s (%d task(s))%s"
                      % (step["id"], step["phaseId"], step["taskCount"],
                         "" if not step["renamedFrom"]
                         else " [renamed from %s]" % (step["renamedFrom"],)))
    return manifest, report


def apply_drop(manifest, pid, reason, now):
    """Archive a proposal. Returns (manifest, message) or (None, why)."""
    prop = find_proposal(manifest, pid)
    if prop is None:
        return None, "no proposal %s in this manifest" % (pid,)
    if prop.get("status") == "materialized":
        return None, ("%s is materialized as %s - dropping the record would "
                      "orphan the history trail"
                      % (pid, prop.get("materializedAs") or "a phase"))
    if not str(reason or "").strip():
        return None, ("a drop needs a reason: a dropped proposal is history "
                      "rather than a deletion, and an archive that cannot say "
                      "why cannot be read later")
    prop["status"] = "dropped"
    prop["notes"] = str(reason).strip()
    prop["droppedAt"] = now
    return manifest, "%s dropped: %s" % (pid, prop["notes"])


def apply_revive(manifest, pid):
    """Put a dropped proposal back in play, keeping why it was dropped."""
    prop = find_proposal(manifest, pid)
    if prop is None:
        return None, "no proposal %s in this manifest" % (pid,)
    if prop.get("status") != "dropped":
        return None, ("%s is %r, not dropped - only a dropped proposal can be "
                      "revived" % (pid, prop.get("status")))
    prop["status"] = "proposed"
    prop["droppedAt"] = None
    return manifest, ("%s revived; its drop reason is kept as history: %s"
                      % (pid, (prop.get("notes") or "").strip()))


# --- orchestration: lock, apply, revalidate, write ------------------------------
def _save(path, manifest):
    """Write the manifest back in whatever layout it arrived in."""
    if _mio.is_sharded(_mio.read_json(path)):
        _mio.save_sharded(path, manifest)
    else:
        _mio.atomic_write_json(path, manifest)


def _revalidate(manifest):
    """The validator's own verdict, imported rather than shelled out to."""
    import _manifest_rules
    return _manifest_rules.validate(manifest)


def iso_now():
    """Wall clock, isolated so nothing above reaches for one.

    `now(timezone.utc)` rather than `utcnow()`: that spelling is deprecated and
    warns on every call, while `datetime.UTC` needs 3.11 and this tree holds a 3.8
    floor.
    """
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def run(mpath, verb, pids, policy=None, reason=None, now=None):
    """Do it, under the lock, and refuse rather than write something invalid.

    Returns `(ok, payload)`; `payload` carries `plan`/`message`/`warnings` on
    success and `findings` on refusal - the shape both doors render.

    Revalidation happens BEFORE the write, so a manifest that would be invalid
    never reaches disk and a refusal leaves no half-applied state behind.
    """
    now = now or iso_now()
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        return False, {"findings": ["cannot read %s: %s" % (mpath, exc)]}
    if not isinstance(manifest, dict):
        return False, {"findings": ["%s is not an object" % (mpath,)]}

    if verb == "plan":
        return True, {"plan": plan_for(manifest, pids)}

    plan = None
    if verb == "materialize":
        if policy == "with-deps":
            ordered = []
            for pid in pids:
                for step in closure(manifest, pid):
                    if step not in ordered:
                        ordered.append(step)
            pids = ordered
        plan = plan_for(manifest, pids, policy)
        if plan["refused"] and not plan["steps"]:
            return False, {"findings": ["%s: %s" % (b["id"], b["reason"])
                                        for b in plan["refused"]]}
        if plan["needsDecision"]:
            return False, {"findings": [
                "%s waits on %s, which is still parked. Materialize both "
                "(--with-deps) or cut the edge (--drop-edges) - this does not "
                "guess which you meant." % (pids[0], ", ".join(plan["pulledIn"]))]}

    project = os.path.dirname(os.path.abspath(mpath)) or "."
    handle = _locks.acquire(project, LOCK_NAME, note="proposal:" + verb)
    try:
        if verb == "materialize":
            manifest, message = apply_materialize(manifest, plan, now)
        elif verb == "drop":
            manifest, message = apply_drop(manifest, pids[0], reason, now)
        elif verb == "revive":
            manifest, message = apply_revive(manifest, pids[0])
        else:
            return False, {"findings": ["unknown verb %r" % (verb,)]}
        if manifest is None:
            return False, {"findings": [message]}
        findings, warnings = _revalidate(manifest)
        if findings:
            return False, {"findings": ["the result would be invalid, so nothing "
                                        "was written"] + list(findings)}
        _save(mpath, manifest)
    finally:
        if isinstance(handle, dict):
            _locks.release(project, LOCK_NAME, out=lambda *_a, **_k: None)
    return True, {"message": message, "warnings": warnings}


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
        print("_proposals.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__proposals.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
