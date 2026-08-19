#!/usr/bin/env python3
"""
The two questions asked of the ledger AS A WHOLE rather than of a slice of it:
how much spend the attribution layers actually resolved (`coverage`), and the
calendar-month roll-up of ledger spend beside plan progress (`monthly_activity`).

One of four passes cut out of `_usage_analytics.py` (U3.2) on its own
`# --- coverage and monthly activity ---` marker, every body moved by line
range. The two share a file because that is the section they shared, and
because neither reads the other.

`coverage` exists so that a dashboard where 90% of spend is `unattributed`
says so instead of quietly showing one big bucket as if it were your phases.
`monthly_activity` is the ONE computation site behind the 12-month overview's
three surfaces - report table, panel card, CLI - so their numbers cannot drift
apart, and it derives `bugsFixed` the way `audit-status.effective_bug_status`
derives 'fixed' rather than trusting a status field.

Reads `_usage_core` and nothing else in the tree; `usage_ledger.py` re-exports
every public name defined here, so no call site names this module.

This module carries no `--selftest` of its own; its 18 cases live in
`plugins/audit/tests/test__usage_coverage.py`, the moved labels byte-identical -
see `plugins/audit/tests/_harness.py`.
"""
import os
import sys
import time

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

import _usage_core as _core  # noqa: E402  (the arithmetic under every pass here)
from _usage_core import parse_ts, task_index  # noqa: E402  (one ISO parse, one plan index)

# Thin module-level aliases, not copies: the bodies below moved out of
# `_usage_analytics.py` by line range, and an alias keeps them reading the same
# names while there is still exactly ONE definition of each, one layer down.
_tokens = _core._tokens
_cost = _core._cost

POOR_COVERAGE_PCT = 50.0


# --- coverage and monthly activity ----------------------------------------------
def coverage(rows):
    """How much spend the attribution layers actually resolved.

    A dashboard where 90% is `unattributed` is not showing you your phases — it is
    showing you one big bucket. This drives a visible warning rather than letting
    every other chart quietly mean nothing."""
    by_attr, total = {}, 0
    for row in rows:
        n = _tokens(row)
        total += n
        by_attr[row.get("attr") or "unattributed"] = \
            by_attr.get(row.get("attr") or "unattributed", 0) + n
    if not total:
        return {"total": 0, "byAttr": {}, "attributedPct": 0.0,
                "taskLevelPct": 0.0, "warn": False}
    unattributed = by_attr.get("unattributed", 0)
    return {
        "total": total,
        "byAttr": {k: round(100.0 * v / total, 1) for k, v in by_attr.items()},
        "attributedPct": round(100.0 * (total - unattributed) / total, 1),
        "taskLevelPct": round(100.0 * by_attr.get("task", 0) / total, 1),
        "warn": (100.0 * unattributed / total) > POOR_COVERAGE_PCT,
    }


MONTHLY_PLAN_KEYS = ("tasksCompleted", "bugsReported", "bugsFixed",
                     "phasesMerged")


def _event_month(value):
    """ISO timestamp -> 'YYYY-MM' in UTC, or None when unparseable.

    Parsed through parse_ts rather than sliced, so an offset timestamp lands in
    its UTC month and garbage lands nowhere instead of in a bucket named after
    its first seven characters."""
    epoch = parse_ts(value)
    if epoch is None:
        return None
    g = time.gmtime(epoch)
    return "%04d-%02d" % (g.tm_year, g.tm_mon)


def _month_span(first, last):
    """Inclusive list of 'YYYY-MM' from first to last."""
    out = []
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    while (y, m) <= (ly, lm):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def monthly_activity(manifest, rows, months=12):
    """Calendar-month roll-up of ledger spend AND plan progress — the ONE
    computation site behind the 12-month overview's three surfaces (report
    table, panel card, CLI), so their numbers cannot drift apart.

    ledger: {month: {tokens, costUSD, msgs}} from `rows`.
    plan:   {month: {tasksCompleted, bugsReported, bugsFixed, phasesMerged}}
            from the manifest — tasksCompleted counts DONE tasks by their
            `completedAt` month, bugsReported by `bug.reportedAt`, phasesMerged
            by `phase.mergedAt`. bugsFixed is DERIVED the way
            audit-status.effective_bug_status derives 'fixed': a bug whose
            linked task (`bug.taskId`) is done, bucketed by THAT task's
            completedAt — and a wontfix bug never counts.

    `months[]` is zero-filled between the first and last month seen on either
    side, then trimmed to the LAST `months` entries (None/0 = no cap). Both
    dicts carry exactly the months in `months[]`, zero-filled, so renderers
    never have to .get() around holes.
    """
    ledger_acc = {}
    for r in (rows or []):
        m = _event_month((r.get("ts") or "") + ":00:00Z")
        if m is None:
            continue
        slot = ledger_acc.setdefault(m, {"tokens": 0, "costUSD": 0.0,
                                         "msgs": 0})
        slot["tokens"] += _tokens(r)
        slot["costUSD"] += _cost(r)
        try:
            slot["msgs"] += int(r.get("msgs") or 0)
        except (TypeError, ValueError):
            pass

    plan_acc = {}

    def bump(month, key):
        if not month:
            return
        slot = plan_acc.setdefault(month, {k: 0 for k in MONTHLY_PLAN_KEYS})
        slot[key] += 1

    tasks = task_index(manifest)
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        bump(_event_month(ph.get("mergedAt")), "phasesMerged")
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("status") == "done":
                bump(_event_month(t.get("completedAt")), "tasksCompleted")
    for b in ((manifest or {}).get("bugs") or []):
        if not isinstance(b, dict):
            continue
        bump(_event_month(b.get("reportedAt")), "bugsReported")
        if b.get("status") == "wontfix":
            continue
        t = tasks.get(b.get("taskId")) if b.get("taskId") else None
        if isinstance(t, dict) and t.get("status") == "done":
            bump(_event_month(t.get("completedAt")), "bugsFixed")

    seen = sorted(set(ledger_acc) | set(plan_acc))
    if not seen:
        return {"months": [], "ledger": {}, "plan": {}}
    span = _month_span(seen[0], seen[-1])
    if months and len(span) > months:
        span = span[-months:]
    ledger = {}
    plan = {}
    for m in span:
        got = ledger_acc.get(m) or {"tokens": 0, "costUSD": 0.0, "msgs": 0}
        ledger[m] = {"tokens": got["tokens"],
                     "costUSD": round(got["costUSD"], 6),
                     "msgs": got["msgs"]}
        plan[m] = plan_acc.get(m) or {k: 0 for k in MONTHLY_PLAN_KEYS}
    return {"months": span, "ledger": ledger, "plan": plan}


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_coverage.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_coverage.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
