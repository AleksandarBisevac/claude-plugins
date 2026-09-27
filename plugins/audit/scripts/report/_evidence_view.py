#!/usr/bin/env python3
"""
Everything the report says about test execution, read straight from the ledger.

The same shape as `_usage_load.py`, and for the same reason: this is the ONLY
piece of the evidence feature that touches a file. Every renderer below it takes
the dict this returns and gives back a string, which is the house rule about
pushing I/O to the edges applied to the one part of the report that has to read
a directory nobody passed in.

RETURNS None WHEN THE PLAN POINTS AT NO RUN AT ALL, and that is a contract rather
than a convenience. The badge column is not earned, the drawer grows no third
group, the Markdown twin gains no column, and a manifest written before any of
this existed renders BYTE FOR BYTE as it did - which is what
`tools/check-rendered-artifacts.py` compares the committed example against. The
Usage section already keeps exactly this promise for exactly this reason: a
section that draws an empty frame to a scale nobody measured is worse than a
section that is not there.

THE LEDGER IS THE SOURCE OF TRUTH AND THE POINTER IS A CACHE. The manifest's
`testEvidence` block says WHICH run to look up; everything rendered - the verdict,
what ran, whether the tree moved, whether the gate touched anything this task
owns - is read off the row that run wrote. A pointer naming a run this checkout
does not hold is therefore its own state, `Pointer without evidence`, and not a
silence: the plan is referring to a record that is not here, and that is news.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__evidence_view.py` - see `plugins/audit/tests/_harness.py`.
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

import _evidence_io  # noqa: E402  (where a run's record lives, and how to read it)
import _manifest_io as _mio  # noqa: E402  (declared_gate_entries: the one reading of a gate)
import _report_html  # noqa: E402  (the vocabulary and the view, decided once)
import _status_facts  # noqa: E402  (evidence_gap: the ONE rule that says whether an absence is excused)


# --- where this manifest's record lives ---------------------------------------
# THE RESOLUTION MOVED DOWN TO `_evidence_io`, where its own docstring already
# said it belonged ("where the directory is is still `_evidence_io`'s to
# decide"). `audit-status.py` needs the same answer to date this plan's evidence
# boundary, and a second expression of "which project and which config point at
# THIS manifest's record" would let the gate and the report read two different
# ledgers for one plan. The name is kept here because it is what this module's
# own cases and its one caller below spell.
_project_and_config = _evidence_io.project_config_for


# --- reading the plan ---------------------------------------------------------
def subjects(manifest):
    """`(tasks, phases)` - every holder a pointer may sit on, in plan order.

    `tasks` is `[(task, phase), ...]` because a task's gate question needs BOTH:
    a task with no `tests.gate` is measured by its phase's `testGate`, and reading
    only the task would report "no gate configured" for work a gate really does
    grade. `phases` is the phase bodies themselves, which carry the sign-off run.
    """
    tasks, phases = [], []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        phases.append(phase)
        for task in (phase.get("tasks") or []):
            if isinstance(task, dict):
                tasks.append((task, phase))
    return tasks, phases


def _pointed_at_anything(tasks, phases):
    """Whether the plan names a single recorded run.

    THE PREDICATE THAT KEEPS AN OLD REPORT BYTE-IDENTICAL. It reads pointers and
    nothing else - not gates, not the ledger - because a plan that DECLARES gates
    it has never run would otherwise earn a column full of `No evidence` on every
    manifest written before this feature existed.
    """
    for task, _phase in tasks:
        if _report_html.tev_pointer(task):
            return True
    return any(_report_html.tev_pointer(p) for p in phases)


def _rows_for(rows, scope, subject_id):
    """Every recorded run for one subject, newest first.

    BY `ts` AND NOT BY FILE ORDER, which is `_evidence_io.latest_by_subject`'s
    rule and is adopted rather than re-decided: rows land in one file per writer
    per month, so two worktrees produce two files whose concatenation is in no
    meaningful order at all.
    """
    mine = [r for r in rows
            if isinstance(r, dict) and r.get("scope") == scope
            and str(r.get("taskId") if scope == "task" else r.get("phaseId"))
            == str(subject_id)]
    return sorted(mine, key=lambda r: str(r.get("ts") or ""), reverse=True)


def _view_for(holder, phase, scope, by_run, rows, boundary=None,
              read_error=None):
    """One holder's view, with the runs before it attached.

    The current run is dropped from the history by RUN ID rather than by position:
    the pointer does not have to name the newest row - a refused pointer write
    leaves the plan behind the record on purpose, and `--reconcile` is the repair -
    so slicing the list would hide a run or repeat one.

    `boundary` is `_evidence_io`'s block, or None when nobody computed one. IT IS
    NOT READ HERE - it is handed straight to `_status_facts.evidence_gap`, which
    is the SAME function `rollup` buckets the gate's verdict with. A renderer that
    compared `completedAt` against `at` itself would be a second opinion about
    which absences are excused, free to disagree with the exit code the reader is
    holding; and the direction it would disagree in is silent, because a badge
    that excuses more than the gate does turns neglect into a green-looking page.

    `read_error` is the caller's failed ledger read, handed to `tev_view` so a
    pointer whose run could not be looked up says so instead of dangling.
    """
    pointer = _report_html.tev_pointer(holder)
    row = by_run.get(str(pointer.get("runId"))) if pointer else None
    # At phase scope the phase's own declaration, through the one normaliser -
    # an all-blank `testGate` runs nothing, so it is no gate here either.
    configured = (_report_html.tev_configured(holder, phase) if scope == "task"
                  else bool(_mio.declared_gate_entries(holder.get("testGate"))))
    view = _report_html.tev_view(
        pointer, row, configured,
        gap=_status_facts.evidence_gap(holder, scope, boundary),
        basis=(boundary or {}).get("basis"), read_error=read_error)
    # A GROUP MEMBER'S POINTER IS ITS CARRIER'S RUN, and saying so is the whole
    # difference between "graded" and "measured here": rendered bare it would
    # claim a sign-off run for this phase that nobody made.
    carrier = _status_facts.graded_by(holder)
    if carrier and pointer:
        view["gradedBy"] = carrier
        view["why"] = "graded by %s's run %s - %s" % (carrier, pointer.get("runId"),
                                                       view.get("why") or "")
    # ...and a phase signed off with a recorded reason and no run says the reason
    # where the badge's basis goes, rather than only that no run was recorded.
    review = holder.get("review") if isinstance(holder.get("review"), dict) else {}
    # The commits a group took into its review outside every task, with the
    # reason: the one place a later reader can see what the sign-off accepted.
    accepted = [a for a in (review.get("acceptedCommits") or [])
                if isinstance(a, dict) and a.get("commit")]
    if scope == "phase" and accepted:
        view["acceptedCommits"] = accepted
    if scope == "phase" and not pointer and review.get("noEvidenceReason"):
        view["why"] = "signed off with no gate run, and the reason recorded: %s. %s" % (
            review["noEvidenceReason"], view.get("why") or "")
    subject = holder.get("id")
    if subject:
        current = str((row or {}).get("runId") or "")
        view["history"] = [r for r in _rows_for(rows, scope, subject)
                           if str(r.get("runId") or "") != current]
    return view


def _phase_full_row(raw, own_view):
    """One phase's `fullRun` entry for the report, or None.

    `raw` is the caller's own per-phase answer (`answer`/`basis`/`runId`, plus
    `head`/`mergedHead`/`phaseId`/`testGateBasis` - render-report.py computes it
    at layer 7, the same way it computes `boundary`, and this module never reads
    git or a second copy of the ledger to get there).

    THE SUITE COUNTS AND THE SIGN-OFF STAMP COME FROM `own_view`'S OWN ROW,
    never re-read from the ledger a second time: `own_view` is this SAME phase's
    sign-off view, already built by `_view_for` two lines above the call site, and
    its `row` is the ledger row the phase's OWN gate last recorded. A `derived`
    run narrows to a subset it counts as `narrowed`; a `wide` one still counts
    what it WOULD have narrowed to, as `shadow` - the same two keys, so reading
    either first and falling back to the second answers "how many suites, out of
    how many" regardless of which mode this phase's gate runs in.
    """
    if not isinstance(raw, dict):
        return None
    out = dict(raw)
    row = own_view.get("row") if isinstance(own_view, dict) else None
    if isinstance(row, dict):
        counts = row.get("narrowed") or row.get("shadow") or {}
        out["listed"] = counts.get("listed")
        out["full"] = counts.get("full")
        out["signOffStatus"] = row.get("status")
        out["signOffTs"] = row.get("ts")
    return out


# --- the load -----------------------------------------------------------------
def load_evidence(manifest, manifest_path, project_dir=None, boundary=None,
                  full_run=None):
    """Everything the report says about test execution, or None when it says none.

    `{"tasks", "phases", "keys", "flags", "rows", "files", "unreadable",
    "readError"}`:

      tasks   {taskId: view}  - one per task, whether or not it points at a run
      phases  {phaseId: {"own": view, "rollup": [(key, label, count), ...][,
              "fullRun": {...}]}} - the phase's OWN sign-off run and an
              aggregate over its tasks, kept apart because merging them would
              claim a measurement nobody made; `fullRun` is a THIRD measurement,
              present only for a phase `full_run` names at all
      keys    the distinct statuses across the TASK views, in vocabulary order
      flags   the distinct observation markers across them, in vocabulary order

    `keys` and `flags` are what the filter chips are built from, and they are read
    off the views rather than off the vocabulary: a chip for a status no row in
    this plan reached is a control whose every use is a no-op, which is the defect
    the one-author Author cell and the unpinned sort select already refuse.

    Fail-soft in one direction only. A ledger that cannot be read leaves every
    pointer `ledger-unreadable` rather than silently clean - and not `dangling`
    either, because "the run is not here" is a claim only a read can make.
    `readError` carries the failure (`_report_html.tev_read_error`'s shape, the
    one the panel ships too) and `files`/`unreadable` are None beside it: a
    count of a read nobody made is not zero, it is unknown. A read that worked
    carries `readError` None and its real counts.

    `boundary` ARRIVES AS AN ARGUMENT AND IS NEVER DERIVED HERE, which is the rule
    `rollup` already follows one module over and it matters more here. The caller
    computes ONE block and hands the same object to both, so the badge a reader
    sees and the verdict the gate reached rest on the same moment rather than on
    two reads of a ledger that a parallel run may have grown between. None is the
    third state, not a default: a caller that computed no boundary excuses
    nothing, which is exactly what every caller rendered before this existed.

    `full_run` IS THE SAME KIND OF ARGUMENT, ONE FIELD OVER: render-report.py's own
    `{phaseId: {"answer", ...}}`, or None when it computed none (a plan naming no
    `meta.fullGate` at all). `None` and `{}` read the same here - no phase earns a
    `fullRun` key, which is what keeps a report of a plan naming no third place
    byte-identical.
    """
    tasks, phases = subjects(manifest)
    if not _pointed_at_anything(tasks, phases):
        return None
    project, config = _project_and_config(manifest_path, project_dir)
    read_error = None
    try:
        read = _evidence_io.read_rows(project, config=config)
    except Exception as exc:
        read, read_error = {"rows": []}, "%s" % (exc,)
    rows = [r for r in (read.get("rows") or []) if isinstance(r, dict)]
    by_run = {}
    for row in rows:
        run = str(row.get("runId") or "")
        if run:
            by_run[run] = row
    task_views = {}
    for task, phase in tasks:
        tid = task.get("id")
        if tid:
            task_views[str(tid)] = _view_for(task, phase, "task", by_run, rows,
                                             boundary, read_error)
    phase_views = {}
    for phase in phases:
        pid = phase.get("id")
        if not pid:
            continue
        mine = [task_views[str(t.get("id"))] for t in (phase.get("tasks") or [])
                if isinstance(t, dict) and str(t.get("id")) in task_views]
        own_view = _view_for(phase, phase, "phase", by_run, rows, boundary,
                             read_error)
        entry = {"own": own_view, "rollup": _report_html.tev_rollup(mine)}
        full_row = _phase_full_row((full_run or {}).get(str(pid)), own_view)
        if full_row is not None:
            entry["fullRun"] = full_row
        phase_views[str(pid)] = entry
    return {
        "tasks": task_views,
        "phases": phase_views,
        "keys": _ordered(set(v["key"] for v in task_views.values()),
                         _report_html.TEV_ORDER),
        "flags": _ordered(set(k for v in task_views.values()
                              for k, _w in v["flags"]),
                          tuple(_report_html.TEV_FLAG_LABELS)),
        "rows": len(rows),
        "files": None if read_error is not None else (read.get("files") or 0),
        "unreadable": (None if read_error is not None
                       else (read.get("unreadable") or 0)),
        "readError": (None if read_error is None
                      else _report_html.tev_read_error(read_error)),
    }


def _ordered(present, vocabulary):
    """The values actually present, in the vocabulary's order, unknowns last.

    Not `sorted()`: alphabetical order would put `cancelled` ahead of `passed`,
    which reads as a ranking nobody chose. A word the vocabulary does not carry
    still gets a chip - the schema promises the status enum may gain members - and
    it goes at the end, sorted, so its position says "this build did not know it"
    rather than implying a place in the order.
    """
    known = [v for v in vocabulary if v in present]
    return known + sorted(v for v in present if v not in vocabulary)


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
        print("_evidence_view.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__evidence_view.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
