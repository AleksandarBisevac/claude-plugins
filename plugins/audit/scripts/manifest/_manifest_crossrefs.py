#!/usr/bin/env python3
"""
Everything that asks how one part of the manifest REFERS to another.

Split out of `_manifest_rules.py`, and this is the seam the file's own
`# --- validate: one walk, then one question per piece ---` marker drew: the
phase walk builds an index, and then five checks read it and nothing else. Each
of them is a question about a reference - does this id name one thing, does this
`blockedBy` resolve, can this wait ever be satisfied, does the fileIndex agree
with the tasks in both directions, is the task <-> bug link reciprocal, does a
parked proposal reserve an id the live plan already spends.

THE INDEX IS THE ARGUMENT, WHICH IS WHY THIS COULD BE CUT OUT AT ALL. Every
function here takes the dict `_manifest_phases._walk_phases` returns (plus, for
three of them, the manifest) and returns its own `(findings, warnings)` pair. No
accumulator is shared, no order is depended on, and every one of them can be
called from a case with a hand-built index and no manifest anywhere near it.

`_cycle_findings` came along because `_check_refs_and_cycles` is the only thing
that calls it, and the two halves are one question asked twice: a reference that
names nothing can never be satisfied, and a reference that names something in a
cycle can never be satisfied either.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_crossrefs.py` - see
`plugins/audit/tests/_harness.py`.
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

import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _manifest_io as _mio  # noqa: E402  (the id -> status map, and what 'satisfied' means)
import _priority  # noqa: E402  (the ONE expression of execution order and its rules)
import _ado_parent as _parent  # noqa: E402  (where each item hangs, and whether it can)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
BUG_ID_RE = _vocab.BUG_ID_RE
BUG_STATUS = _vocab.BUG_STATUS
KNOWN_BUG = _vocab.KNOWN_BUG
KNOWN_PROPOSAL = _vocab.KNOWN_PROPOSAL
PROPOSAL_STATUS = _vocab.PROPOSAL_STATUS
PROP_ID_RE = _vocab.PROP_ID_RE
_check_ado = _vocab._check_ado
_require_fields = _vocab._require_fields
_safe_list = _vocab._safe_list
_strip_line_suffix = _vocab._strip_line_suffix
_unknown_keys = _vocab._unknown_keys


# --- the bugs half of the index --------------------------------------------------
def _index_bugs(manifest):
    """The bugs[] half of the index — `bug_list`, `bug_ids`, `bug_by_id`.

    Separate from `_check_bugs` because two checks need it BEFORE the bug rules
    run: the duplicate-id sweep unions bug ids with phase and task ids, and the
    proposals' reserved-id rule counts a bug id as a live id. An index is not a
    check — this function reports nothing and cannot fail, which is why it
    returns a plain dict rather than a pair.
    """
    bugs = manifest.get("bugs")
    bug_list = bugs if isinstance(bugs, list) else []
    return {"bug_list": bug_list,
            "bug_ids": [b.get("id") for b in bug_list
                        if isinstance(b, dict) and b.get("id")],
            "bug_by_id": {b["id"]: b for b in bug_list
                          if isinstance(b, dict) and b.get("id")}}


def _live_ids(index):
    """Every id the live plan spends: phases, then tasks, then bugs, in
    document order and WITH duplicates — `_check_unique_ids` is the thing that
    finds those, so this must not quietly dedupe them away."""
    return index["phase_ids"] + index["task_ids"] + index["bug_ids"]


# --- ids, references and cycles --------------------------------------------------
def _check_unique_ids(index):
    """One id names one thing. Returns (findings, warnings); warnings is always
    empty.

    Phases, tasks and bugs share ONE namespace because `blockedBy` resolves
    against phase and task ids together — a phase and a task wearing the same
    id make every reference to it ambiguous, and the orchestrator would follow
    whichever the lookup happened to reach.
    """
    f = []
    seen = set()
    for i in _live_ids(index):
        if i in seen:
            f.append("duplicate id: %s" % i)
        seen.add(i)
    return (f, [])


def _ref_findings(refs_val, where, field, universe, kind):
    """Report a non-array value, a non-string entry (which would crash
    the set-membership test), or an unresolved id — never raise.

    Was a closure inside `validate()`, REDEFINED once per phase over the shared
    findings list. A free function returning its own list is the same three
    rules with nothing captured, and it can be called from a case with five
    arguments and no manifest anywhere near it.
    """
    findings = []
    if refs_val is not None and not isinstance(refs_val, list):
        findings.append("%s: %s must be an array, got %s"
                        % (where, field, type(refs_val).__name__))
    for ref in _safe_list(refs_val):
        if not isinstance(ref, str):
            findings.append("%s: %s entry must be a string id, got %r"
                            % (where, field, ref))
        elif ref not in universe:
            findings.append("%s: %s '%s' does not resolve to %s"
                            % (where, field, ref, kind))
    return findings


def _check_refs_and_cycles(phases, index):
    """Every blockedBy/dependsOn resolves, and the waits-on graph is acyclic.
    Returns (findings, warnings); warnings is always empty.

    The two halves are one piece because they are one question asked twice: a
    reference that names nothing can never be satisfied, and a reference that
    names something in a cycle can never be satisfied either. The universes
    differ on purpose — `blockedBy` may name a phase OR a task, `dependsOn` may
    name only a task.
    """
    f = []
    known = set(index["phase_ids"]) | set(index["task_ids"])
    task_ids = index["task_ids"]

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))
        f.extend(_ref_findings(phase.get("blockedBy"), pwhere, "blockedBy",
                               known, "any task/phase"))
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti)))
            f.extend(_ref_findings(task.get("blockedBy"), twhere, "blockedBy",
                                   known, "any task/phase"))
            f.extend(_ref_findings(task.get("dependsOn"), twhere, "dependsOn",
                                   task_ids, "a task"))

    _cycle_findings(phases, f)
    return (f, [])


def _cycle_findings(phases, findings):
    """Detect dependency cycles over the waits-on graph.

    Edges: task -> its blockedBy/dependsOn targets; phase -> its blockedBy
    targets; phase -> each of its tasks (a phase is done only after its tasks),
    which catches the task-blockedBy-its-own-phase deadlock.
    """
    edges = {}

    def add_edge(a, b):
        if a and b:
            edges.setdefault(a, []).append(b)

    for phase in phases:
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id")
        for ref in _safe_list(phase.get("blockedBy")):
            if isinstance(ref, str):
                add_edge(pid, ref)
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            add_edge(pid, tid)
            for ref in _safe_list(task.get("blockedBy")):
                if isinstance(ref, str):
                    add_edge(tid, ref)
            for ref in _safe_list(task.get("dependsOn")):
                if isinstance(ref, str):
                    add_edge(tid, ref)

    WHITE, GRAY, BLACK = 0, 1, 2
    color, reported = {}, set()
    for start in list(edges):
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(edges.get(start, ())))]
        color[start] = GRAY
        path = [start]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                path.pop()
                color[node] = BLACK
                continue
            c = color.get(nxt, WHITE)
            if c == GRAY:
                i = path.index(nxt) if nxt in path else len(path) - 1
                cyc = path[i:] + [nxt]
                key = frozenset(cyc)
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        "dependency cycle (blockedBy/dependsOn can never be "
                        "satisfied): %s" % " -> ".join(str(x) for x in cyc))
            elif c == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(edges.get(nxt, ()))))
                path.append(nxt)


# --- phase priority --------------------------------------------------------------
def _check_priority(manifest, phases):
    """`phase.priority` — every way a pin can be a claim with nothing behind it.

    Returns (findings, warnings), and the findings list is ALWAYS EMPTY. That is
    the decision, not an omission: a priority is a wish about the schedule, and a
    finding here would make the manifest INVALID — which refuses the next
    `/audit:task add`, reds the `--gate` on the `invalid` condition, and would
    make `set-priority.py --force` roll back the very write it was asked to force.
    The pipeline must keep running past a disagreement about order; what it must
    not do is run past it in silence.

    Four of the five rules live here. The fifth — a `priority` written into a
    SHARD BODY, where nothing will read it — cannot be asked of an assembled
    manifest at all (the value is gone by then), so it is asked by
    `_manifest_io.index_only_in_bodies()` where both halves of the file are open,
    and printed by `validate-manifest.py`.
    """
    w = []
    real = [p for p in (phases or []) if isinstance(p, dict)]

    for pid, value in _priority.invalid_tiers(real):
        w.append("phase %s: priority %r is not a positive integer, so the phase "
                 "is ordered as if it had none - a tier starts at 1"
                 % (pid or "?", value))

    for tier, holders in _priority.tier_conflicts(real):
        w.append("phase %s and %s both hold priority %d, which is the one tier "
                 "that must be unique - %s wins because it comes first in the "
                 "manifest, and that tie-break is what runs until one of them "
                 "is changed"
                 % (holders[0], ", ".join(str(h) for h in holders[1:]), tier,
                    holders[0]))

    # A pin that leans on unfinished work is a claim its own dependencies
    # contradict. Reported for EVERY prioritised phase rather than only the top
    # one: the runtime note (`_status_facts.priority_note`) names the pin that
    # is being skipped right now, and this names the plan that will skip it.
    status = _mio.status_index(manifest)
    for phase in real:
        if _priority.tier_of(phase) is None:
            continue
        if phase.get("status") in _mio.TERMINAL:
            continue
        waiting = _mio.unsatisfied(phase.get("blockedBy"), status)
        if waiting:
            w.append("phase %s holds priority %d but waits on %s (not done) - "
                     "priority re-sorts READY work only, so this phase is "
                     "skipped until the wait clears"
                     % (phase.get("id") or "?", _priority.tier_of(phase),
                        ", ".join(waiting)))
    return ([], w)


# --- where the work hangs on the board -------------------------------------------
def _ado_meta(manifest):
    """`meta.ado`, or None when this manifest has no connector configured."""
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado if isinstance(ado, dict) else None


def _require_parent_warnings(ado, rows):
    """`conventions.requireParent` graded against the PLAN, not against a hunch.

    F-P-18's warning lived in `_manifest_ado`, where only the `ado` block is
    visible, and fired whenever `requireParent` was true and `parentWorkItem`
    was unset. That was right while one integer parented the whole manifest and
    became a FALSE ALARM the moment a phase could declare its own: the commonest
    good config now has no `parentWorkItem` at all. What a bare block can still
    prove stayed there; the question that needs the phases is asked here, and it
    names the items rather than predicting them.

    WARNINGS, never findings, for the reason the tag half already gives: once
    every item is linked a push does UPDATES, the conformance gate runs on
    CREATE only, and the contradiction lies dormant. Calling that setup invalid
    would fail its CI on upgrade over a config that works.
    """
    conventions = ado.get("conventions")
    if not isinstance(conventions, dict) or conventions.get("requireParent") is not True:
        return []
    # `source == "phase"` is EXCLUDED, and not as a convenience. A task under
    # `phaseWorkItems` whose phase is not linked yet resolves to no id because
    # the phase item does not exist YET - the same push creates it and hangs the
    # task under it. Counting those as homeless would report a warning about
    # every task in an unpushed plan, which is the false alarm this whole
    # function was moved here to stop being.
    homeless = [r for r in rows if r["parent"] is None and r["source"] != "phase"]
    if not homeless:
        return []
    return ["meta.ado.conventions.requireParent is true, and %d item(s) resolve "
            "to no parent at all (%s) - the conformance gate refuses a CREATE "
            "without one, so a push would create nothing for them. Give each an "
            "`adoParent`, set meta.ado.parentWorkItem as the fallback, or drop "
            "requireParent."
            % (len(homeless),
               ", ".join("%s %s" % (r["kind"], r["id"] or "?")
                         for r in homeless[:6]))]


def _check_ado_parents(manifest, phases):
    """Where every item would hang, and whether that place can be true.

    Returns (findings, warnings), and the split is the whole decision:

      TIER A -> FINDINGS. Structural, offline, and it always has a basis: an
      item under itself, or under something this manifest already hangs under
      it. Nothing outside this file is needed to know that is impossible, so
      calling the manifest invalid is honest. It is also the tier that catches
      the live bug - ADO does NOT check an API-created parent link against the
      process hierarchy, so a Product Backlog Item whose parent is its own Task
      exists on a real board right now.

      TIER B -> WARNINGS. It reads `meta.ado.hierarchy`, which is a CACHE with a
      `fetchedAt`: refusing a whole manifest on evidence that may be a month old
      would fail a CI run over a stale file, and the loud stop already exists at
      push time. Equal rank is a note there and a note here.

    NOT VERIFIED IS SILENT HERE, and only here. `validate()` is run on every
    manifest write; a line per link saying the type ranks were never fetched
    would arrive hundreds of times and teach people to skip warnings. The place
    it is counted and printed is where the decision is being made - the push
    plan, and `resolve-ado-parent.py`.
    """
    ado = _ado_meta(manifest)
    if ado is None:
        return ([], [])
    inv = _parent.inventory(phases, ado)
    hierarchy = ado.get("hierarchy")
    levels = hierarchy.get("levels") if isinstance(hierarchy, dict) else None
    result = _parent.hierarchy_violations(
        inv["rows"], levels if isinstance(levels, dict) else None)
    findings = [e["message"] for e in result["refusals"] if e["tier"] == "A"]
    warnings = list(inv["warnings"])
    warnings.extend(e["message"] for e in result["refusals"] if e["tier"] != "A")
    warnings.extend(e["message"] for e in result["warnings"])
    warnings.extend(_require_parent_warnings(ado, inv["rows"]))
    return (findings, warnings)


# --- fileIndex, bugs and proposals -----------------------------------------------
def _check_file_index(manifest, index):
    """fileIndex integrity in BOTH directions. Returns (findings, warnings);
    warnings is always empty.

    Forward: every task id a fileIndex entry names must exist. Backward: every
    file a task claims must appear under that task in the index. Only the
    second direction catches the common drift — a task gaining a file without
    the index being updated — and it is the direction a schema cannot express.

    An absent or non-dict fileIndex is silent: the key is optional, and its
    wrong-type diagnostic is not this function's to give twice.
    """
    f = []
    file_index = manifest.get("fileIndex")
    if not isinstance(file_index, dict):
        return (f, [])

    task_ids = index["task_ids"]
    stripped_index = {}
    for fpath, refs in file_index.items():
        key = _strip_line_suffix(fpath)
        bucket = stripped_index.setdefault(key, set())
        if not isinstance(refs, list):
            f.append("fileIndex['%s']: value must be an array of task ids, "
                     "got %s" % (fpath, type(refs).__name__))
            continue
        for ref in refs:
            if isinstance(ref, str):
                bucket.add(ref)  # only hashable str ids enter the set
            if ref not in task_ids:
                f.append("fileIndex['%s']: task '%s' does not exist" % (fpath, ref))
    for tid, files in index["task_files"].items():
        for fentry in files:
            key = _strip_line_suffix(fentry)
            if tid not in stripped_index.get(key, set()):
                f.append("task %s: file '%s' missing from fileIndex "
                         "(fileIndex['%s'] must include '%s')"
                         % (tid, fentry, key, tid))
    return (f, [])


def _check_bugs(manifest, index):
    """bugs[] shape and vocabulary, and the RECIPROCAL task <-> bug link.

    Returns (findings, warnings). Both directions of the link are checked from
    here because a one-sided link is invisible from either end alone: a bug
    naming a task whose bugId names a different bug is two records that each
    look fine and disagree about which fix belongs to which report.
    """
    f, w = [], []
    bugs = manifest.get("bugs")
    if bugs is not None and not isinstance(bugs, list):
        f.append("bugs: not an array")
    task_ids = index["task_ids"]
    for bi, bug in enumerate(index["bug_list"]):
        if not isinstance(bug, dict):
            f.append("bugs[%d]: not an object" % bi)
            continue
        bid = bug.get("id")
        bwhere = "bug %s" % (bid or ("bugs[%d]" % bi))
        _require_fields(bug, bwhere, f)
        _unknown_keys(bug, KNOWN_BUG, bwhere, w)
        if bid and not BUG_ID_RE.match(str(bid)):
            f.append("%s: id must match BUG-<number>" % bwhere)
        if bug.get("status") not in BUG_STATUS:
            f.append("%s: status %r not in %s" % (bwhere, bug.get("status"), list(BUG_STATUS)))
        _check_ado(bug, bwhere, f)
        if bug.get("taskId"):
            if bug["taskId"] not in task_ids:
                f.append("%s: taskId '%s' does not resolve to a task" % (bwhere, bug["taskId"]))
            else:
                linked = index["task_by_id"].get(bug["taskId"]) or {}
                if linked.get("bugId") != bid:
                    f.append("%s: taskId '%s' but that task's bugId is %r — "
                             "link must be reciprocal"
                             % (bwhere, bug["taskId"], linked.get("bugId")))

    for twhere, tid, bug_ref in index["bug_links"]:
        if bug_ref not in index["bug_ids"]:
            f.append("%s: bugId '%s' does not resolve to a bug" % (twhere, bug_ref))
        else:
            linked = index["bug_by_id"].get(bug_ref) or {}
            if linked.get("taskId") != tid:
                f.append("%s: bugId '%s' but that bug's taskId is %r — "
                         "link must be reciprocal"
                         % (twhere, bug_ref, linked.get("taskId")))
    return (f, w)


def _check_proposals(manifest, index):
    """proposals[] — parked phases (/audit:init park + /audit:propose).

    Returns (findings, warnings). Two classes of entry share this array.
    Payload-bearing proposals are structured records the /audit:propose
    lifecycle depends on — their vocabulary IS enforced (findings). Legacy
    free-form entries (pre-0.33) are tolerated: unknown-key warnings at most,
    so no old manifest goes red.
    """
    f, w = [], []
    proposals = manifest.get("proposals")
    if proposals is not None and not isinstance(proposals, list):
        f.append("proposals: not an array")
    prop_list = proposals if isinstance(proposals, list) else []
    phase_ids = index["phase_ids"]
    live_ids = set(_live_ids(index))
    prop_ids_seen = set()
    reserved_ids = set()   # payload phase+task ids across still-parked proposals
    staged_refs = []       # (where, ref) — blockedBy/dependsOn inside payloads
    for xi, prop in enumerate(prop_list):
        if not isinstance(prop, dict):
            f.append("proposals[%d]: not an object" % xi)
            continue
        prid = prop.get("id")
        xwhere = "proposal %s" % (prid or ("proposals[%d]" % xi))
        _unknown_keys(prop, KNOWN_PROPOSAL, xwhere, w)
        if prid:
            if prid in prop_ids_seen:
                f.append("duplicate proposal id: %s" % prid)
            prop_ids_seen.add(prid)
        payload = prop.get("payload")
        if "payload" in prop and payload is not None and not isinstance(payload, dict):
            f.append("%s: payload must be an object or null, got %s"
                     % (xwhere, type(payload).__name__))
            payload = None
        if not isinstance(payload, dict):
            continue  # legacy free-form entry — tolerated as-is
        if not PROP_ID_RE.match(str(prid or "")):
            f.append("%s: id must match PROP-<number>" % xwhere)
        status = prop.get("status")
        if status not in PROPOSAL_STATUS:
            f.append("%s: status %r not in %s"
                     % (xwhere, status, list(PROPOSAL_STATUS)))
        mat = prop.get("materializedAs")
        if mat is not None:
            if mat not in phase_ids:
                f.append("%s: materializedAs '%s' does not resolve to a phase"
                         % (xwhere, mat))
            if status != "materialized":
                f.append("%s: materializedAs is set but status is %r — must be "
                         "'materialized' (/audit:propose writes both together)"
                         % (xwhere, status))
        # The DROP pair, mirroring the materialize pair above. `propose.md` has
        # always asked for the justification, but prose cannot enforce it and the
        # panel can drop too now — an archive whose entries do not say WHY is a
        # tombstone, and the command's own words are that a later reader must
        # find why the work was declined.
        notes = prop.get("notes")
        if status == "dropped" and not str(notes or "").strip():
            f.append("%s: status is 'dropped' but there is no `notes` "
                     "justification — a dropped proposal is history rather than a "
                     "deletion, so it has to say why the work was declined"
                     % (xwhere,))
        dropped_at = prop.get("droppedAt")
        if dropped_at is not None and status != "dropped":
            f.append("%s: droppedAt is set but status is %r — must be 'dropped'"
                     % (xwhere, status))
        pphase = payload.get("phase")
        if not isinstance(pphase, dict):
            f.append("%s: payload.phase must be an object (the parked phase), "
                     "got %s" % (xwhere, type(pphase).__name__))
            continue
        for key in ("id", "title"):
            if not pphase.get(key):
                f.append("%s: payload.phase missing required '%s'" % (xwhere, key))
        if not isinstance(pphase.get("tasks"), list):
            f.append("%s: payload.phase.tasks must be an array — park the full "
                     "synthesized phase so materialization is a move, not a "
                     "rebuild" % xwhere)
        # Reserved-id bookkeeping applies only while the proposal is parked: a
        # materialized payload id now living as a real phase is the SUCCESS
        # state, not a collision, and a dropped proposal releases its ids.
        if status == "proposed":
            staged = [pphase.get("id")] + [
                t.get("id") for t in _safe_list(pphase.get("tasks"))
                if isinstance(t, dict)]
            for sid in staged:
                if not sid:
                    continue
                if sid in live_ids:
                    f.append("%s: reserved id '%s' collides with a live id — "
                             "/audit:propose materialize re-allocates on "
                             "collision, but a parked payload should never "
                             "share an id with the live plan" % (xwhere, sid))
                elif sid in reserved_ids:
                    f.append("%s: reserved id '%s' is already reserved by "
                             "another proposal" % (xwhere, sid))
                reserved_ids.add(sid)
            for ref in _safe_list(pphase.get("blockedBy")):
                if isinstance(ref, str):
                    staged_refs.append((xwhere, ref))
            for t in _safe_list(pphase.get("tasks")):
                if not isinstance(t, dict):
                    continue
                for field in ("blockedBy", "dependsOn"):
                    for ref in _safe_list(t.get(field)):
                        if isinstance(ref, str):
                            staged_refs.append((xwhere, ref))
    # Staged refs resolve against the live plan OR any reserved id — a payload
    # may lean on a sibling proposal. Naming nothing anywhere is only a warning:
    # the payload is staged, not live, and materialize re-checks refs anyway.
    staged_universe = live_ids | reserved_ids
    for xwhere, ref in staged_refs:
        if ref not in staged_universe:
            w.append("%s: staged blockedBy/dependsOn '%s' names nothing in the "
                     "live plan or any parked proposal — materialize will ask "
                     "about it" % (xwhere, ref))
    return (f, w)

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
        print("_manifest_crossrefs.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_crossrefs.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
