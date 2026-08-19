#!/usr/bin/env python3
"""
What the work cost, and what the plan said it could: `unit_economics`,
`cost_bands`/`band_of`, `phase_budgets`, `retry_cost`.

One of four passes cut out of `_usage_analytics.py` (U3.2) on its own
`# --- cost per unit of work ---` marker, every body moved by line range.

Three guards live here and each exists because the cheap version of the number
would be worse than none. A projection off three samples is noise, so
`unit_economics` suppresses it below `MIN_TASKS_FOR_PROJECTION` and reports a
p25-p75 RANGE rather than a point estimate when it does speak. A phase with no
declared budget renders as nothing - defaulting it to zero would paint every
unbudgeted phase as infinitely over, and defaulting it to the spend would paint
every one as exactly on target. And retried spend and blocked spend are reported
SEPARATELY, never summed into a "waste" figure: the ledger buckets by hour, not
by attempt, so a task that took three attempts and then landed did not waste
three attempts' worth.

`COST_BAND_PARAMS` is the one statement of the relative basis's shape.
`panel-server.py` serialises that exact dict into the panel page, so `panel.js`
cannot restate it differently - keep it JSON-serializable.

Reads `_usage_core` and nothing else in the tree; `usage_ledger.py` re-exports
every public name defined here, so no call site names this module.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_economics.py`, the moved labels byte-identical -
see `plugins/audit/tests/_harness.py`.
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

import _usage_core as _core  # noqa: E402  (the arithmetic under every pass here)
from _usage_core import task_index  # noqa: E402  (the plan index these all start from)

# Thin module-level aliases, not copies: the bodies below moved out of
# `_usage_analytics.py` by line range, and an alias keeps them reading the same
# names while there is still exactly ONE definition of each, one layer down.
_cost = _core._cost

MIN_TASKS_FOR_PROJECTION = 5


# --- cost per unit of work ------------------------------------------------------
def _percentile(values, p):
    """Nearest-rank percentile on a sorted list. Stdlib only, no numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[idx]


def unit_economics(manifest, rows):
    """Cost per completed task, and what the remaining work would cost at that rate.

    The projection is SUPPRESSED below `MIN_TASKS_FOR_PROJECTION` completed tasks and
    is always a p25-p75 RANGE rather than a point estimate. A confident forecast off
    three samples is worse than no forecast."""
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)
    done = [c for tid, c in cost_by_task.items()
            if (tasks.get(tid) or {}).get("status") == "done"]
    remaining = sum(1 for t in tasks.values()
                    if t.get("status") in ("pending", "in_progress", "blocked"))
    out = {
        "completed": len(done), "remaining": remaining,
        "gate": MIN_TASKS_FOR_PROJECTION, "sufficient": len(done) >= MIN_TASKS_FOR_PROJECTION,
        "costPerTask": round(sum(done) / len(done), 4) if done else None,
        "p25": None, "p75": None, "projection": None,
        "mostExpensive": sorted(
            ((tid, round(c, 4), (tasks.get(tid) or {}).get("attempts"))
             for tid, c in cost_by_task.items() if tid in tasks),
            key=lambda x: -x[1])[:5],
    }
    if not out["sufficient"]:
        return out
    p25, p75 = _percentile(done, 25), _percentile(done, 75)
    out["p25"], out["p75"] = round(p25, 4), round(p75, 4)
    out["projection"] = {"low": round(p25 * remaining, 2),
                         "high": round(p75 * remaining, 2)}
    return out


BAND_ORDER = ("typical", "high", "outlier")

# The ONE place the relative basis's shape is stated: the sample gate and the two
# percentiles cost_bands() reads below. panel.js no longer restates these numbers
# — panel-server.py serializes this exact dict into the page (__COST_BAND_PARAMS__)
# so a change here cannot silently leave the panel classifying tasks differently
# from the report. Keep it JSON-serializable (plain int values only): it crosses
# the Python/JS boundary as-is via json.dumps.
COST_BAND_PARAMS = {
    "gate": MIN_TASKS_FOR_PROJECTION,
    "percentileHigh": 50,
    "percentileOutlier": 90,
}


def cost_bands(manifest, rows, cfg=None):
    """Sort tasks into `typical` / `high` / `outlier` by what they cost.

    Deliberately NOT called a risk band: manifest tasks already carry `risk`, which
    is the risk of the CHANGE (and is what `routing` compares within). Two different
    axes wearing one word would make both impossible to discuss.

    The thresholds are the project's own median and p90 by default, so this means
    something on day one with no configuration and re-calibrates as the work grows.
    A team with a real budget can pin absolute numbers in
    `usage.bands.{highUSD,outlierUSD}` instead; `basis` says which is in force, and
    the callers print the thresholds, because a band whose definition is invisible
    is a number nobody can argue with.

    Two guards:

    * Below `MIN_TASKS_FOR_PROJECTION` completed tasks the relative basis returns
      NOTHING — percentiles off three samples are noise, and a confidently wrong
      band is worse than no band. The absolute basis has no such gate: a configured
      threshold is an opinion the user already holds.
    * Thresholds come from COMPLETED tasks only, because a half-finished task's cost
      is not comparable. They are then applied to every task including in-flight
      ones, which is what lets the metering hook warn while there is still time to
      act.
    """
    band_cfg = ((cfg or {}).get("bands") or {}) if isinstance(cfg, dict) else {}
    tasks = task_index(manifest)
    cost_by_task = {}
    for row in rows:
        tid = row.get("taskId")
        if tid and tid in tasks:
            cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)

    out = {"basis": None, "high": None, "outlier": None, "byTask": {},
           "counts": {b: 0 for b in BAND_ORDER}, "sample": 0,
           "gate": COST_BAND_PARAMS["gate"], "sufficient": False}

    hi, out_ = band_cfg.get("highUSD"), band_cfg.get("outlierUSD")
    try:
        hi = float(hi) if hi is not None else None
        out_ = float(out_) if out_ is not None else None
    except (TypeError, ValueError):      # a garbled config must not classify
        hi = out_ = None
    if hi is not None and out_ is not None and 0 < hi <= out_:
        out.update(basis="absolute", high=hi, outlier=out_, sufficient=True)
    else:
        done = [c for tid, c in cost_by_task.items()
                if (tasks.get(tid) or {}).get("status") == "done"]
        out["sample"] = len(done)
        if len(done) < COST_BAND_PARAMS["gate"]:
            return out
        out.update(basis="relative", sufficient=True,
                   high=round(_percentile(done, COST_BAND_PARAMS["percentileHigh"]), 4),
                   outlier=round(_percentile(done, COST_BAND_PARAMS["percentileOutlier"]), 4))

    for tid, cost in cost_by_task.items():
        band = ("outlier" if cost > out["outlier"]
                else "high" if cost > out["high"] else "typical")
        out["byTask"][tid] = band
        out["counts"][band] += 1
    return out


def phase_budgets(manifest, rows):
    """Spend against `phase.budgetUSD`, for the phases that declare one.

    Ties spend to the PLAN rather than to the calendar, which is the comparison a
    manifest-driven pipeline can make and a date-range dashboard cannot.

    Phases without a budget are returned too, with `budget: None` — the surfaces
    need to render them as "—". Defaulting an absent budget to zero would paint
    every unbudgeted phase as infinitely over, and defaulting it to the spend
    would paint every one as exactly on target; both are lies about a phase whose
    owner simply never set a number.

    `pct` is uncapped on purpose: a phase at 130% should read 130%, not a bar
    pinned at full with the overrun hidden."""
    spent = {}
    for row in rows:
        pid = row.get("phaseId") or "--"
        spent[pid] = spent.get(pid, 0.0) + _cost(row)

    out, budgeted, total_budget, total_spent = [], 0, 0.0, 0.0
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict) or not ph.get("id"):
            continue
        pid = ph["id"]
        raw = ph.get("budgetUSD")
        budget = (float(raw) if isinstance(raw, (int, float))
                  and not isinstance(raw, bool) and raw > 0 else None)
        used = round(spent.get(pid, 0.0), 4)
        if budget is not None:
            budgeted += 1
            total_budget += budget
            total_spent += used
        out.append({
            "id": pid, "title": ph.get("title") or "", "status": ph.get("status"),
            "budget": budget, "spent": used,
            "pct": round(100.0 * used / budget, 1) if budget else None,
            "over": bool(budget and used > budget),
        })
    return {"phases": out, "budgeted": budgeted,
            "totalBudget": round(total_budget, 4) if budgeted else None,
            "totalSpent": round(total_spent, 4) if budgeted else None,
            "anyOver": any(p["over"] for p in out)}


def band_of(bands, task_id):
    """The band for one task, or None when banding is suppressed/unknown."""
    if not bands or not bands.get("sufficient"):
        return None
    return (bands.get("byTask") or {}).get(task_id)


def retry_cost(manifest, rows):
    """Spend on retried tasks and spend on blocked tasks — reported SEPARATELY.

    These are not summed into a single "waste" figure and the retried number is not
    called waste at all. The ledger buckets by hour, not by attempt, so there is no
    per-attempt token boundary: a task that took three attempts and then landed did
    not waste three attempts' worth. Only the BLOCKED number is unambiguous spend
    with no outcome."""
    tasks = task_index(manifest)
    total = retried = blocked = 0.0
    retried_ids, blocked_ids = set(), set()
    for row in rows:
        c = _cost(row)
        total += c
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        try:
            attempts = int(t.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts > 1:
            retried += c
            retried_ids.add(tid)
        if t.get("status") == "blocked":
            blocked += c
            blocked_ids.add(tid)
    return {
        "totalCost": round(total, 4),
        "retriedCost": round(retried, 4), "retriedTasks": len(retried_ids),
        "retriedPct": round(100.0 * retried / total, 1) if total else 0.0,
        "blockedCost": round(blocked, 4), "blockedTasks": len(blocked_ids),
        "blockedPct": round(100.0 * blocked / total, 1) if total else 0.0,
        # Explicit so no renderer is tempted to add the two together.
        "overlaps": len(retried_ids & blocked_ids),
    }


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_economics.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_economics.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
