#!/usr/bin/env python3
"""
Everything that asks how one part of the manifest REFERS to another.

Split out of `_manifest_rules.py`, and this is the seam the file's own
`# --- validate: one walk, then one question per piece ---` marker drew: the
phase walk builds an index, and the checks below read it and nothing else. Each
of them is a question about a reference - does this id name one thing, does this
`blockedBy` resolve, can this wait ever be satisfied, does the fileIndex agree
with the tasks in both directions, is the task <-> bug link reciprocal, does a
recorded decision say what was decided and by whom, does a parked proposal
reserve an id the live plan already spends. `validate()` in `_manifest_rules.py`
is the list of them; a count written here would be a second one.

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
import json
import os
import re
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
import _id_refs  # noqa: E402  (FINDING_LISTS: the lists a review holds findings in)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
BUG_ID_RE = _vocab.BUG_ID_RE
BUG_STATUS = _vocab.BUG_STATUS
DEC_ID_RE = _vocab.DEC_ID_RE
KNOWN_BUG = _vocab.KNOWN_BUG
KNOWN_DECISION = _vocab.KNOWN_DECISION
STATUS = _vocab.STATUS
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


# --- the decisions half of the index ---------------------------------------------
def _index_decisions(manifest):
    """The decisions[] half of the index — `decision_list`, `decision_ids`,
    `decision_by_id`.

    Shaped exactly like `_index_bugs` and separate from `_check_decisions` for
    the same reason: the duplicate-id sweep and the proposals' reserved-id rule
    both need the ids BEFORE the decision rules run. An index is not a check; it
    reports nothing and cannot fail.
    """
    decisions = manifest.get("decisions")
    dec_list = decisions if isinstance(decisions, list) else []
    return {"decision_list": dec_list,
            "decision_ids": [d.get("id") for d in dec_list
                             if isinstance(d, dict) and d.get("id")],
            "decision_by_id": {d["id"]: d for d in dec_list
                               if isinstance(d, dict) and d.get("id")}}


def _live_ids(index):
    """Every id the live plan spends: phases, then tasks, then bugs, then
    decisions, in document order and WITH duplicates — `_check_unique_ids` is the
    thing that finds those, so this must not quietly dedupe them away.

    A CALLER MAY NOT HAVE THE DECISIONS. `_index_decisions` is a separate
    contribution to the index, and cases hand-build an index with the keys the
    check under test needs; reading the key through `.get` keeps a decision-free
    index a legal argument rather than a `KeyError` in an unrelated check.
    """
    return (index["phase_ids"] + index["task_ids"] + index["bug_ids"]
            + list(index.get("decision_ids") or []))


# --- ids, references and cycles --------------------------------------------------
def _check_unique_ids(index):
    """One id names one thing. Returns (findings, warnings); warnings is always
    empty.

    Phases, tasks, bugs and decisions share ONE namespace because `blockedBy`
    resolves against phase, task and decision ids together — a phase and a task
    wearing the same id make every reference to it ambiguous, and the
    orchestrator would follow whichever the lookup happened to reach.

    A BUG IS IN THE NAMESPACE AND NOT IN THE BLOCKER UNIVERSE, which is the one
    asymmetry here and is deliberate. `_manifest_io.status_index` holds phases,
    tasks and decisions, so each of those can reach a TERMINAL status and clear a
    wait; nothing puts a bug id in that map, so a `blockedBy` naming one would
    resolve and then never settle. A dependency that cannot be cleared is a row
    that lies about what the plan is waiting for, so the reference stays a
    finding — the id is reserved here so nothing else may take it, and
    `_check_refs_and_cycles` is where the universe is drawn.
    """
    f = []
    seen = set()
    for i in _live_ids(index):
        if i in seen:
            f.append(_output.finding("crossrefs.unique_ids.value", "duplicate id: %s" % i))
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
        findings.append(_output.finding("crossrefs.%s.not-array" % (field,), "%s: %s must be an array, got %s"
                        % (where, field, type(refs_val).__name__)))
    for ref in _safe_list(refs_val):
        if not isinstance(ref, str):
            findings.append(_output.finding("crossrefs.%s.entry-not-string" % (field,), "%s: %s entry must be a string id, got %r"
                            % (where, field, ref)))
        elif ref not in universe:
            findings.append(_output.finding("crossrefs.%s.unresolved" % (field,), "%s: %s '%s' does not resolve to %s"
                            % (where, field, ref, kind)))
    return findings


def _check_refs_and_cycles(phases, index):
    """Every blockedBy/dependsOn resolves, and the waits-on graph is acyclic.
    Returns (findings, warnings); the warnings are the review findings below.

    The two halves are one piece because they are one question asked twice: a
    reference that names nothing can never be satisfied, and a reference that
    names something in a cycle can never be satisfied either. The universes
    differ on purpose — `blockedBy` may name a phase, a task OR a decision,
    `dependsOn` may name only a task.

    A DECISION JOINED THE `blockedBy` UNIVERSE AND NOTHING ELSE DID. The rule for
    admitting a kind is not that it has an id: it is that
    `_manifest_io.status_index` can say whether it is settled, because a
    reference the resolver cannot clear is a wait the plan can never leave. A
    decision carries the same status vocabulary a task does, so it qualifies; a
    bug carries its own and does not, and a dependency on another session has no
    row in this file at all, so both stay findings and are named as such rather
    than resolving to nothing.

    A REVIEW FINDING'S `fixTask` IS A REFERENCE TOO, answered as a WARNING: it
    names the task whose commit settled the finding, and one naming no task is a
    finding `reopen` can never reach - but it blocks nothing, and a plan whose
    hand-recorded finding points at a since-removed task is still a plan.
    """
    f, w = [], []
    known = (set(index["phase_ids"]) | set(index["task_ids"])
             | set(index.get("decision_ids") or []))
    task_ids = index["task_ids"]

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))
        f.extend(_ref_findings(phase.get("blockedBy"), pwhere, "blockedBy",
                               known, "any task/phase/decision"))
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti)))
            f.extend(_ref_findings(task.get("blockedBy"), twhere, "blockedBy",
                                   known, "any task/phase/decision"))
            f.extend(_ref_findings(task.get("dependsOn"), twhere, "dependsOn",
                                   task_ids, "a task"))
        w.extend(_fix_task_warnings(phase, pwhere, task_ids))

    _cycle_findings(phases, f)
    return (f, w)


def _fix_task_warnings(phase, pwhere, task_ids):
    """One coded warning per review finding whose `fixTask` names no task."""
    review = phase.get("review")
    if not isinstance(review, dict):
        return []
    out = []
    for key in _id_refs.FINDING_LISTS:
        for entry in _safe_list(review.get(key)):
            fix = entry.get("fixTask") if isinstance(entry, dict) else None
            if fix is None or fix in task_ids:
                continue
            out.append(_output.finding(
                "crossrefs.fix_task.unresolved",
                "%s: review.%s finding %s names fixTask %r, which is no task in "
                "this plan - the fix it records cannot be looked up, and a "
                "re-open of that task would not reach it"
                % (pwhere, key, entry.get("id"), fix)))
    return out


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
                        _output.finding("crossrefs.cycle_findings.value", "dependency cycle (blockedBy/dependsOn can never be "
                        "satisfied): %s" % " -> ".join(str(x) for x in cyc)))
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
        if _mio.effective_phase_status(phase) in _mio.TERMINAL:
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

    This warning used to live in `_manifest_ado`, where only the `ado` block is
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
               _output.some_of(["%s %s" % (r["kind"], r["id"] or "?")
                                for r in homeless]))]


def _bug_parent_warnings(ado, bugs):
    """`requireParent` against the ONE kind a push creates and never parents.

    This is the half `_require_parent_warnings` structurally cannot
    answer. That function reads `_parent.inventory`'s rows, and the inventory is
    deliberately called WITHOUT bugs there - bug rows in front of the homeless
    count would report a warning about a link push was never going to create.
    Correct, and it left the validator blind to the case where that same fact is
    the whole problem: with `requireParent` on, the gate refused every bug
    CREATE, and the refusal arrived after the plan and after the confirm rather
    than here, where the contradiction actually lives.

    So this asks the bugs directly and asks a different question of them. Not
    "where does this bug hang" - nowhere, by design, and `_ado_parent` says so
    with a basis - but "this board demands something the connector cannot
    supply", which is U-FIELDS' shape one rule over: the standard is expressible
    and unmeetable, and the only useful moment to say so is before the push.

    A WARNING, never a finding, for the reason its neighbour gives: an
    already-linked plan does UPDATES, the conformance gate runs on CREATE only,
    and calling a working setup invalid would fail its CI on upgrade. LINKED
    BUGS ARE EXCLUDED for that same reason and it is the whole filter - a bug
    with an `ado.id` is an update, and no card is about to be created without a
    parent on its account.
    """
    conventions = ado.get("conventions")
    if not isinstance(conventions, dict) or conventions.get("requireParent") is not True:
        return []
    pending = [bug.get("id") or "?" for bug in (bugs if isinstance(bugs, list) else [])
               if isinstance(bug, dict) and not _linked(bug)]
    if not pending:
        return []
    return ["meta.ado.conventions.requireParent is true, and a push creates a "
            "bug card with no parent link at all - %d bug(s) are not linked "
            "yet (%s), so for those this board asks for something the "
            "connector cannot supply. Phases (and tasks, with phaseWorkItems "
            "off) get the resolved parent and no third kind does; "
            "meta.ado.parentWorkItem is the AUDIT's own branch and does not "
            "reach a bug. Their creates are no longer refused over it - parent "
            "those cards by hand once they exist, or drop requireParent."
            % (len(pending), _output.some_of(pending))]


def _linked(item):
    """Does this item already carry a work item id? A push UPDATES those.

    Spelled here rather than borrowed from `_ado_parent._work_item_id`, which
    is that module's private and answers a stricter question (a POSITIVE id,
    for a graph edge). The question here is only whether a CREATE is still
    coming, and a malformed link is `_manifest_ado`'s finding to report.
    """
    link = item.get("ado")
    return isinstance(link, dict) and link.get("id") is not None


def _check_ado_parents(manifest, phases):
    """Where every item would hang, and whether that place can be true.

    Returns (findings, warnings), and the split is the whole decision:

      A LOOP AN AUTHORED `adoParent` PUT THERE -> FINDING. Structural, offline,
      and it always has a basis: an item under itself, or under something this
      manifest already hangs under it. Nothing outside this file is needed to
      know that is impossible. It is the tier that catches the live bug - ADO
      does NOT check an API-created parent link against the process hierarchy,
      so a Product Backlog Item whose parent is its own Task exists on a real
      board right now.

      A LOOP INHERITED FROM `meta.ado.parentWorkItem` -> WARNING, and this is a
      COMPATIBILITY decision rather than a judgement about severity. That key
      predates this feature, so a manifest nobody has edited can describe such a
      loop - and `COMPATIBILITY.md` promises that a file which validates keeps
      validating for the whole major line. Failing it here would break that
      promise for a file its author never touched. NOTHING IS LOST: the push
      still refuses to create the link, with the same message, because
      `resolve-ado-parent.py` reads `refusals` and a MANIFEST is not a PAYLOAD.
      A board that cannot be built still cannot be built.

      TIER B -> WARNINGS. It reads `meta.ado.hierarchy`, which is a CACHE with a
      `fetchedAt`: invalidating a whole manifest on evidence that may be a month
      old would fail a CI run over a stale file, and the loud stop already exists
      at push time. Equal rank is a note there and a note here.

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
    # ONE KEY EACH, and no subtraction. `_ado_parent` grades both surfaces in
    # one place precisely so this call site does not re-derive a severity: the
    # split by tier that used to live on these two lines could not see the
    # thing that actually decides it, which is whether an AUTHORED `adoParent`
    # is in the loop at all.
    # THE ENTRY'S OWN CODE IS THE RULE. `_ado_parent` already names each
    # hierarchy rule (A1 self-parent, A2 loop, A3 phase-phase loop), so the
    # finding carries that and not a second name for the same rule.
    findings = [_output.finding("crossrefs.ado_parents.%s" % (e["code"],),
                                e["message"])
                for e in result["findings"]]
    warnings = list(inv["warnings"])
    warnings.extend(e["message"] for e in result["warnings"])
    warnings.extend(_require_parent_warnings(ado, inv["rows"]))
    # The bugs are asked SEPARATELY and never through the inventory above, whose
    # `bugs` argument stays unpassed on purpose - see `_bug_parent_warnings`.
    warnings.extend(_bug_parent_warnings(ado, manifest.get("bugs")))
    return (findings, warnings)


# --- fileIndex, bugs and proposals -----------------------------------------------
# The one wording that says a task's `files` and the `fileIndex` disagree. A
# CONSTANT because a second reader grades it differently: `task.files` lives in the
# phase shard and `fileIndex` lives in the index, and `orchestrator.md` forbids a
# task commit from staging the index — so a mid-phase commit CANNOT carry both
# halves, and `_invariants.manifest_revalidated` has to tell this finding apart
# from every other one. Matching the sentence in two files by hand is how
# the two would drift; one of them owns the words.
FILEINDEX_PAIRING = "missing from fileIndex"


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
            f.append(_output.finding("crossrefs.file_index.value-array-task", "fileIndex['%s']: value must be an array of task ids, "
                     "got %s" % (fpath, type(refs).__name__)))
            continue
        for ref in refs:
            if isinstance(ref, str):
                bucket.add(ref)  # only hashable str ids enter the set
            if ref not in task_ids:
                f.append(_output.finding("crossrefs.file_index.task-does-exist", "fileIndex['%s']: task '%s' does not exist" % (fpath, ref)))
    for tid, files in index["task_files"].items():
        for fentry in files:
            key = _strip_line_suffix(fentry)
            if tid not in stripped_index.get(key, set()):
                f.append(_output.finding("crossrefs.file_index.file-fileindex-include", "task %s: file '%s' %s "
                         "(fileIndex['%s'] must include '%s')"
                         % (tid, fentry, FILEINDEX_PAIRING, key, tid)))
    return (f, [])


# --- a bug value's type, read off the published schema ------------------------
# `validate-manifest.py` applies no JSON Schema, and the strict CI step does, so
# a bug value typed one way by the schema and never checked here passed every
# local gate and failed CI. The types are READ from the schema at check time
# rather than restated in a table, so a property the schema gains is typed here
# with no edit. The reader knows the keywords the bug item is written in; any
# other constraint keyword is reported as uncheckable, never taken as a pass.
PLAN_SCHEMA_REL = ("schema", "audit-plan.schema.json")
SCHEMA_READ = frozenset(["$ref", "type", "enum", "items", "oneOf", "anyOf",
                         "pattern", "properties", "required",
                         "additionalProperties"])
SCHEMA_ANNOTATIONS = frozenset(["description", "title", "default", "examples",
                                "$comment", "deprecated", "readOnly",
                                "writeOnly", "$id", "$schema"])
_JSON_TYPE_NAMES = ((bool, "boolean"), (int, "integer"), (float, "number"),
                    (str, "string"), (list, "array"), (dict, "object"))


def load_plan_schema(root=None):
    """The shipped manifest schema, parsed. Raises OSError/ValueError."""
    path = os.path.join(root or _output.PLUGIN_ROOT, *PLAN_SCHEMA_REL)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def json_type(value):
    """The JSON type name of a parsed value (`null` for None)."""
    if value is None:
        return "null"
    for pytype, name in _JSON_TYPE_NAMES:
        if isinstance(value, pytype):
            return name
    return type(value).__name__


def _type_admits(name, value):
    got = json_type(value)
    if name == "number":
        return got in ("integer", "number")
    if name == "integer" and got == "number":
        return float(value).is_integer()
    return got == name


def _schema_parts(node, doc, depth=0):
    """`node` as the list of schema objects that must ALL hold: a `$ref` is
    followed and its siblings kept as a second part, since JSON Schema reads
    them as a conjunction. A ref that cannot be followed becomes a part
    carrying a keyword outside SCHEMA_READ, so it is reported, not passed."""
    if not isinstance(node, dict) or "$ref" not in node:
        return [node]
    ref = node["$ref"]
    siblings = dict((k, v) for k, v in node.items() if k != "$ref")
    target = doc
    if isinstance(ref, str) and ref.startswith("#/") and depth < 32:
        for part in ref[2:].split("/"):
            target = target.get(part) if isinstance(target, dict) else None
    else:
        target = None
    parts = ([{"$ref (unresolved)": ref}] if not isinstance(target, dict)
             else _schema_parts(target, doc, depth + 1))
    return parts + ([siblings] if siblings else [])


def schema_admitted(node, doc):
    """The words for what `node` admits, e.g. ['string', 'array of string']."""
    words = []
    for part in _schema_parts(node, doc):
        if not isinstance(part, dict):
            continue
        names = part.get("type")
        names = [names] if isinstance(names, str) else list(names or [])
        items = part.get("items")
        for name in names:
            if name == "array" and isinstance(items, dict):
                name = "array of %s" % "/".join(schema_admitted(items, doc))
            words.append(name)
        if "enum" in part:
            words.append("one of %s" % json.dumps(part["enum"]))
        for combiner in ("oneOf", "anyOf"):
            for arm in part.get(combiner) or []:
                words.extend(schema_admitted(arm, doc))
    return words


def _arm_types(node, doc):
    names = []
    for part in _schema_parts(node, doc):
        got = part.get("type") if isinstance(part, dict) else None
        names.extend([got] if isinstance(got, str) else list(got or []))
    return names


def _value_class(value):
    """JSON Schema compares numbers by value (1.0 equals 1); a boolean is
    never a number, although Python's bool is an int."""
    got = json_type(value)
    return "number" if got == "integer" else got


def _in_enum(value, enum):
    return any(_value_class(v) == _value_class(value) and v == value
               for v in enum)


def ecma_pattern(pattern):
    """`pattern` compiled to read as ajv reads it (`new RegExp(p, 'u')`) on the
    constructs the schema uses: `\\d` is ASCII only, and a trailing `$` is the
    end of the string, not the end of a last line. Python's defaults differ on
    both, so `BUG-1` plus a newline, or with a non-ASCII digit, would match."""
    if pattern.endswith("$"):
        body = pattern[:-1]
        escapes = len(body) - len(body.rstrip("\\"))
        if escapes % 2 == 0:
            pattern = body + r"\Z"
    return re.compile(pattern, re.ASCII)


def schema_check(node, value, doc, where, depth=0):
    """(reasons, unread) for `value` against the schema `node`.

    `reasons` are findings naming `where`; `unread` is the set of constraint
    keywords met on the way that this reader does not interpret."""
    reasons, unread = [], set()
    for part in _schema_parts(node, doc):
        r, u = _check_schema_part(part, value, doc, where, depth)
        reasons.extend(r)
        unread |= u
    return reasons, unread


def _check_schema_part(part, value, doc, where, depth):
    if part is True or part == {}:
        return [], set()
    if not isinstance(part, dict):
        return [_output.finding("crossrefs.bugs.schema-false",
                                "%s: the schema admits no value here" % where)], set()
    unread = set(k for k in part
                 if k not in SCHEMA_READ and k not in SCHEMA_ANNOTATIONS)
    reasons = []
    names = part.get("type")
    if names is not None:
        names = [names] if isinstance(names, str) else list(names)
        if not any(_type_admits(n, value) for n in names):
            reasons.append(_output.finding(
                "crossrefs.bugs.schema-type", "%s is %s, the schema admits %s"
                % (where, json_type(value), ", ".join(schema_admitted(part, doc)))))
    if "enum" in part and not _in_enum(value, part["enum"]):
        reasons.append(_output.finding(
            "crossrefs.bugs.schema-enum", "%s %s is not one of %s"
            % (where, json.dumps(value), json.dumps(part["enum"]))))
    if ("pattern" in part and isinstance(value, str)
            and not ecma_pattern(part["pattern"]).search(value)):
        reasons.append(_output.finding(
            "crossrefs.bugs.schema-pattern",
            "%s %r does not match the schema's pattern %s"
            % (where, value, part["pattern"])))
    if "items" in part and isinstance(value, list):
        for i, item in enumerate(value):
            r, u = schema_check(part["items"], item, doc,
                                "%s[%d]" % (where, i), depth + 1)
            reasons.extend(r)
            unread |= u
    if isinstance(value, dict):
        r, u = _check_schema_object(part, value, doc, where, depth)
        reasons.extend(r)
        unread |= u
    for combiner in ("oneOf", "anyOf"):
        if combiner not in part:
            continue
        verdicts = [schema_check(arm, value, doc, where, depth + 1)
                    for arm in part[combiner]]
        for _r, u in verdicts:
            unread |= u
        passing = [not r for r, _u in verdicts].count(True)
        # An arm of the value's own type that still failed says WHY (a list
        # holding a number); otherwise the sentence names what is admitted.
        same_type = [r for (r, _u), arm in zip(verdicts, part[combiner])
                     if any(_type_admits(n, value) for n in _arm_types(arm, doc))]
        if passing == 0 and len(same_type) == 1:
            reasons.extend(same_type[0])
        elif passing == 0 or (combiner == "oneOf" and passing > 1):
            reasons.append(_output.finding(
                "crossrefs.bugs.schema-arms", "%s is %s, the schema admits %s%s"
                % (where, json_type(value),
                   ", ".join(schema_admitted(part, doc)) or "nothing",
                   " - and it matches more than one of them"
                   if passing > 1 else "")))
    return reasons, unread


def _check_schema_object(part, value, doc, where, depth):
    reasons, unread = [], set()
    props = part.get("properties") or {}
    for key in part.get("required") or []:
        if key not in value:
            reasons.append(_output.finding(
                "crossrefs.bugs.schema-required",
                "%s.%s is required by the schema" % (where, key)))
    for key in sorted(value):
        if key in props:
            sub = props[key]
        elif "additionalProperties" in part:
            sub = part["additionalProperties"]
        else:
            continue
        if sub is True:
            continue
        if sub is False:
            reasons.append(_output.finding(
                "crossrefs.bugs.schema-additional",
                "%s.%s is not a property the schema allows" % (where, key)))
            continue
        r, u = schema_check(sub, value[key], doc, "%s.%s" % (where, key),
                            depth + 1)
        reasons.extend(r)
        unread |= u
    return reasons, unread


def _bug_item_properties(doc):
    """The bug item's `properties`, reached through the schema's own refs."""
    item = ((doc.get("properties") or {}).get("bugs") or {}).get("items") or {}
    props = {}
    for part in _schema_parts(item, doc):
        if isinstance(part, dict):
            props.update(part.get("properties") or {})
    return props


# A bug value the schema refuses VALIDATED in 3.0.1, so inside the 3.x line it
# is a warning naming the release that refuses it - `COMPATIBILITY.md`,
# *Validation stays additive*, and the `tests.add` path rule before it.
BUG_VALUE_REFUSAL_RELEASE = "4.0.0"


def load_validation_schema(root=None):
    """(schema, findings) for an ENTRY POINT to hand `validate(schema=...)`.

    Loaded where the process starts, so the rules themselves read no file. A
    schema that cannot be read is a FINDING here - the plugin install is broken,
    which is not the user's plan being refused - and the schema comes back as
    False, which `validate()` reads as "the caller tried, and has reported it"."""
    try:
        return load_plan_schema(root), []
    except (OSError, ValueError) as exc:
        return False, [_output.finding(
            "crossrefs.bugs.schema-unreadable",
            "bugs: the plugin's manifest schema could not be read, so no bug "
            "value was type-checked - the install is broken: %s" % (exc,))]


def _fallback_schema(root):
    """(schema or False, warnings) when no caller handed one: the documented
    read for a consumer that loads none. Failing is a WARNING, since the only
    thing lost is the type check the caller did not ask to own."""
    try:
        return load_plan_schema(root), []
    except (OSError, ValueError) as exc:
        return False, [_output.finding(
            "crossrefs.bugs.schema-unavailable",
            "bugs: no schema was handed to validate() and the plugin's could "
            "not be read, so no bug value was type-checked: %s" % (exc,))]


def _bug_value_warnings(bug, bwhere, props, schema, handled):
    """(warnings, unread (property, keyword) pairs) for one bug's values.

    `handled` holds the PATHS (`id`, `ado`, `ado.origin`) a hand-written check
    already refused for this bug; a schema reason at or under one of them is
    that same fault, and is dropped so it is reported once. A sibling path
    (`ado.url` beside a refused `ado.origin`) is a different fault and stays."""
    warnings, unread = [], set()
    for key in bug:
        if key not in props:
            continue
        reasons, kws = schema_check(props[key], bug[key], schema,
                                    "%s: %s" % (bwhere, key))
        unread |= set((key, kw) for kw in kws)
        warnings.extend(
            _output.finding(_output.finding_code(r),
                            "%s - the published schema refuses this value; "
                            "validate-manifest will refuse it from %s (a "
                            "warning in 3.x)" % (r, BUG_VALUE_REFUSAL_RELEASE))
            for r in reasons
            if not any(_at_or_under(r, bwhere, p) for p in handled))
    return warnings, unread


def _at_or_under(reason, bwhere, path):
    """True when the schema reason is about `path` or something inside it."""
    head = "%s: %s" % (bwhere, path)
    return reason.startswith(head) and reason[len(head):len(head) + 1] in (
        " ", ".", "[")


def _fields_reported(new_findings, fields):
    """The fields among `fields` that a just-added finding names in quotes."""
    return set(k for k in fields
               if any(("'%s'" % k) in x for x in new_findings))


# The path each of `_check_ado`'s findings is about, read off its code. A code
# this table does not know is taken to be about the whole `ado` value, which
# suppresses more rather than reporting one fault twice.
_ADO_FINDING_PATHS = {"vocab.ado.ado-object-null": "ado",
                      "vocab.ado.ado-id-integer": "ado.id",
                      "vocab.ado.ado-origin-one": "ado.origin"}


def _check_bugs(manifest, index, schema=None, schema_root=None):
    """bugs[] shape and vocabulary, and the RECIPROCAL task <-> bug link.

    Returns (findings, warnings). Both directions of the link are checked from
    here because a one-sided link is invisible from either end alone: a bug
    naming a task whose bugId names a different bug is two records that each
    look fine and disagree about which fix belongs to which report. Every
    present value is also typed against the schema's bug item, as a warning
    (see BUG_VALUE_REFUSAL_RELEASE).

    `schema` is the parsed schema an entry point loaded
    (`load_validation_schema`); False means it tried and reported the failure
    itself, so nothing is typed and nothing is said twice; None falls back to
    reading the plugin's (or `schema_root`'s) schema, and only when the plan
    holds a bug.
    """
    f, w = [], []
    props, unchecked = {}, set()
    if index["bug_list"]:
        if schema is None:
            schema, unavailable = _fallback_schema(schema_root)
            w.extend(unavailable)
        props = _bug_item_properties(schema) if isinstance(schema, dict) else {}
    bugs = manifest.get("bugs")
    if bugs is not None and not isinstance(bugs, list):
        f.append(_output.finding("crossrefs.bugs.array", "bugs: not an array"))
    task_ids = index["task_ids"]
    for bi, bug in enumerate(index["bug_list"]):
        if not isinstance(bug, dict):
            f.append(_output.finding("crossrefs.bugs.object", "bugs[%d]: not an object" % bi))
            continue
        bid = bug.get("id")
        bwhere = "bug %s" % (bid or ("bugs[%d]" % bi))
        # `handled` is every property a hand-written check below refuses for
        # this bug; the schema's warning for it would be the same fault twice.
        mark = len(f)
        _require_fields(bug, bwhere, f)
        handled = _fields_reported(f[mark:], ("id", "title", "status"))
        _unknown_keys(bug, KNOWN_BUG, bwhere, w)
        if bid and not BUG_ID_RE.match(str(bid)):
            f.append(_output.finding("crossrefs.bugs.id-match-bug", "%s: id must match BUG-<number> or, minted off the development "
                     "branch, BUG-<number>-<suffix>" % bwhere))
            handled.add("id")
        if bug.get("status") not in BUG_STATUS:
            f.append(_output.finding("crossrefs.bugs.status", "%s: status %r not in %s" % (bwhere, bug.get("status"), list(BUG_STATUS))))
            handled.add("status")
        mark = len(f)
        _check_ado(bug, bwhere, f)
        handled |= set(_ADO_FINDING_PATHS.get(_output.finding_code(x), "ado")
                       for x in f[mark:])
        if props:
            value_w, unread = _bug_value_warnings(bug, bwhere, props, schema,
                                                  handled)
            w.extend(value_w)
            unchecked |= unread
        if bug.get("taskId"):
            if bug["taskId"] not in task_ids:
                f.append(_output.finding("crossrefs.bugs.taskid-does-resolve", "%s: taskId '%s' does not resolve to a task" % (bwhere, bug["taskId"])))
            else:
                linked = index["task_by_id"].get(bug["taskId"]) or {}
                if linked.get("bugId") != bid:
                    f.append(_output.finding("crossrefs.bugs.taskid-task-bugid", "%s: taskId '%s' but that task's bugId is %r — "
                             "link must be reciprocal"
                             % (bwhere, bug["taskId"], linked.get("bugId"))))

    # A keyword the reader does not interpret is this plugin being behind its
    # own schema, never a fault in the plan, so it is at most a warning; the
    # build keeps it from shipping (test__manifest_crossrefs, the keyword walk).
    w.extend(_output.finding(
        "crossrefs.bugs.schema-unchecked",
        "bugs[].%s: the schema constrains it with `%s`, which validate-manifest "
        "cannot check - the value was NOT verified against it" % (key, kw))
        for key, kw in sorted(unchecked))
    for twhere, tid, bug_ref in index["bug_links"]:
        if bug_ref not in index["bug_ids"]:
            f.append(_output.finding("crossrefs.bugs.bugid-does-resolve", "%s: bugId '%s' does not resolve to a bug" % (twhere, bug_ref)))
        else:
            linked = index["bug_by_id"].get(bug_ref) or {}
            if linked.get("taskId") != tid:
                f.append(_output.finding("crossrefs.bugs.bugid-bug-taskid", "%s: bugId '%s' but that bug's taskId is %r — "
                         "link must be reciprocal"
                         % (twhere, bug_ref, linked.get("taskId"))))
    return (f, w)


SETTLE_COMMAND = ('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" '
                  'settle')


def _check_derived(manifest):
    """Stored phase and bug values the derivations answer differently.
    Returns (findings, warnings).

    A WARNING AND NEVER A FINDING, because a stale stored value is a plan every
    derived reader still reads correctly - and every plan written before the verbs
    stored these values carries some, so refusing them would turn those plans red on
    upgrade. What it costs is the reader that does not derive (an older plugin's
    hooks, `jq`, an agent reading the file), and the warning says so and names the
    one command that settles the plan.

    ONE WARNING PER RECORD, IN THE `<kind> <id>: <body>` SHAPE, with a body that
    names no id and so is byte-equal across records moving the same way. That is
    what `_warning_groups.collapse` groups: the verbs print these after every write,
    and a plan carrying dozens of stale values reads as one line per kind of move -
    a count, the first ids and the `--verbose` pointer - instead of burying the
    verb's own output. The basis is the rule's, true of every record it names;
    `audit-lookup` prints one record's own.
    """
    rows = _mio.derived_disagreements(manifest)
    if not rows:
        return ([], [])
    return ([], ["%s %s: %s" % (r["kind"], r["id"], _derived_body(r)) for r in rows])


_DERIVED_BASIS = {
    ("phase", "status"): "every task is terminal, a sign-off verdict is recorded "
                         "and any branch has merged",
    ("bug", "status"): "its fix task is done",
    ("bug", "fixedIn"): "its fix task is done at a recorded commit",
}


def _derived_body(row):
    """The id-free body of one stored-against-derived warning."""
    derived = ("that commit" if row["field"] == "fixedIn" else row["derived"])
    return ("stored %s is %s while %s, so it derives %s - a reader of the stored "
            "field alone (an older plugin's hooks, jq, an agent) gets the stale "
            "value; `%s` stores every derived value, under the index lock"
            % (row["field"], row["stored"] if row["stored"] is not None else "empty",
               _DERIVED_BASIS.get((row["kind"], row["field"]), row["basis"]),
               derived, SETTLE_COMMAND))


def _check_decisions(manifest, index):
    """decisions[] shape and vocabulary, and the two fields a SETTLED decision
    owes a reader. Returns (findings, warnings).

    WHY A DECISION IS HELD TO MORE THAN A BUG IS. A bug row is a report and may
    be thin; a decision row is the thing a refusal reads INSTEAD of stopping to
    ask a human, so a `done` decision with no `answer` and nobody named would
    discharge a gate on a blank. That is worse than having no record at all,
    because the gate goes quiet and the reader has nothing to hold it to. So the
    two fields are findings at `done` and are asked of nothing else: an
    unanswered decision is allowed to be unanswered, which is its whole purpose.

    THE STATUS VOCABULARY IS NOT RESTATED HERE. It is `STATUS` — the same words
    a phase and a task carry — because `_manifest_io.status_index` is what
    settles a `blockedBy` naming this row, and a private enum would be a blocker
    nothing could clear.

    A NON-ARRAY `decisions` IS A WARNING AND NOT A FINDING, which is the
    proposals rule one key over and is owed to `COMPATIBILITY.md` rather than
    chosen. That document promises validation stays ADDITIVE: a manifest that
    validated against a release keeps validating against every later one in the
    major line. Root keys this plugin does not know are tolerated, so somebody
    could have left a free-form `decisions` note in a manifest before the key
    meant anything — and a finding would make it invalid on upgrade, which is
    the promise broken by a feature. It is still SAID, because a note sitting
    where a record belongs records nothing and the writer should hear so.
    """
    f, w = [], []
    decisions = manifest.get("decisions")
    if decisions is not None and not isinstance(decisions, list):
        w.append("decisions: not an array, so nothing here is read as a "
                 "decision record - `decisions` is a list of DEC- entries")
    for di, dec in enumerate(index.get("decision_list") or []):
        if not isinstance(dec, dict):
            f.append(_output.finding("crossrefs.decisions.object", "decisions[%d]: not an object" % di))
            continue
        did = dec.get("id")
        dwhere = "decision %s" % (did or ("decisions[%d]" % di))
        _require_fields(dec, dwhere, f)
        _unknown_keys(dec, KNOWN_DECISION, dwhere, w)
        if did and not DEC_ID_RE.match(str(did)):
            f.append(_output.finding("crossrefs.decisions.id-match-dec", "%s: id must match DEC-<number>" % dwhere))
        status = dec.get("status")
        if status not in STATUS:
            f.append(_output.finding("crossrefs.decisions.status", "%s: status %r not in %s"
                     % (dwhere, status, list(STATUS))))
        if status == "done":
            for field, why in (("answer", "an approval with no words is the "
                                          "second-hand approval this record "
                                          "replaces"),
                               ("decidedBy", "an approval nobody is named for "
                                             "cannot be held to anyone")):
                if not str(dec.get(field) or "").strip():
                    f.append(_output.finding("crossrefs.decisions.status-done-empty", "%s: status is \"done\" but %s is empty - %s"
                             % (dwhere, field, why)))
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
        f.append(_output.finding("crossrefs.proposals.array", "proposals: not an array"))
    prop_list = proposals if isinstance(proposals, list) else []
    phase_ids = index["phase_ids"]
    live_ids = set(_live_ids(index))
    prop_ids_seen = set()
    reserved_ids = set()   # payload phase+task ids across still-parked proposals
    staged_refs = []       # (where, ref) — blockedBy/dependsOn inside payloads
    for xi, prop in enumerate(prop_list):
        if not isinstance(prop, dict):
            f.append(_output.finding("crossrefs.proposals.object", "proposals[%d]: not an object" % xi))
            continue
        prid = prop.get("id")
        xwhere = "proposal %s" % (prid or ("proposals[%d]" % xi))
        _unknown_keys(prop, KNOWN_PROPOSAL, xwhere, w)
        if prid:
            if prid in prop_ids_seen:
                f.append(_output.finding("crossrefs.proposals.value", "duplicate proposal id: %s" % prid))
            prop_ids_seen.add(prid)
        payload = prop.get("payload")
        if "payload" in prop and payload is not None and not isinstance(payload, dict):
            f.append(_output.finding("crossrefs.proposals.payload-object-null", "%s: payload must be an object or null, got %s"
                     % (xwhere, type(payload).__name__)))
            payload = None
        if not isinstance(payload, dict):
            continue  # legacy free-form entry — tolerated as-is
        if not PROP_ID_RE.match(str(prid or "")):
            f.append(_output.finding("crossrefs.proposals.id-match-prop", "%s: id must match PROP-<number> or, minted off the development "
                     "branch, PROP-<number>-<suffix>" % xwhere))
        status = prop.get("status")
        if status not in PROPOSAL_STATUS:
            f.append(_output.finding("crossrefs.proposals.status", "%s: status %r not in %s"
                     % (xwhere, status, list(PROPOSAL_STATUS))))
        mat = prop.get("materializedAs")
        if mat is not None:
            if mat not in phase_ids:
                f.append(_output.finding("crossrefs.proposals.materializedas-does-resolve", "%s: materializedAs '%s' does not resolve to a phase"
                         % (xwhere, mat)))
            if status != "materialized":
                f.append(_output.finding("crossrefs.proposals.materializedas-set-status", "%s: materializedAs is set but status is %r — must be "
                         "'materialized' (/audit:propose writes both together)"
                         % (xwhere, status)))
        # The DROP pair, mirroring the materialize pair above. `propose.md` has
        # always asked for the justification, but prose cannot enforce it and the
        # panel can drop too now — an archive whose entries do not say WHY is a
        # tombstone, and the command's own words are that a later reader must
        # find why the work was declined.
        notes = prop.get("notes")
        if status == "dropped" and not str(notes or "").strip():
            f.append(_output.finding("crossrefs.proposals.status-dropped-there", "%s: status is 'dropped' but there is no `notes` "
                     "justification — a dropped proposal is history rather than a "
                     "deletion, so it has to say why the work was declined"
                     % (xwhere,)))
        dropped_at = prop.get("droppedAt")
        if dropped_at is not None and status != "dropped":
            f.append(_output.finding("crossrefs.proposals.droppedat-set-status", "%s: droppedAt is set but status is %r — must be 'dropped'"
                     % (xwhere, status)))
        pphase = payload.get("phase")
        if not isinstance(pphase, dict):
            f.append(_output.finding("crossrefs.proposals.payload-phase-object", "%s: payload.phase must be an object (the parked phase), "
                     "got %s" % (xwhere, type(pphase).__name__)))
            continue
        for key in ("id", "title"):
            if not pphase.get(key):
                f.append(_output.finding("crossrefs.proposals.payload-phase-missing", "%s: payload.phase missing required '%s'" % (xwhere, key)))
        if not isinstance(pphase.get("tasks"), list):
            f.append(_output.finding("crossrefs.proposals.payload-phase-tasks", "%s: payload.phase.tasks must be an array — park the full "
                     "synthesized phase so materialization is a move, not a "
                     "rebuild" % xwhere))
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
                    f.append(_output.finding("crossrefs.proposals.reserved-id-collides", "%s: reserved id '%s' collides with a live id — "
                             "/audit:propose materialize re-allocates on "
                             "collision, but a parked payload should never "
                             "share an id with the live plan" % (xwhere, sid)))
                elif sid in reserved_ids:
                    f.append(_output.finding("crossrefs.proposals.reserved-id-already", "%s: reserved id '%s' is already reserved by "
                             "another proposal" % (xwhere, sid)))
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_manifest_crossrefs.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_crossrefs.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
