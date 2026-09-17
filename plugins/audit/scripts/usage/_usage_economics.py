#!/usr/bin/env python3
"""
What the work cost, and what the plan said it could: `unit_economics`,
`cost_bands`/`band_of`, `phase_budgets`, `retry_cost`. And, since P56.6, what the
PLAN ITSELF costs against the same work done without one: `gate_scope_comparison`,
`gate_reuse_comparison`, `sibling_spend_comparison` and the `plan_cost_claim` that
names which of the three a given history can actually support - see their own
`# --- the plan's own cost ---` section below for why each refuses rather than
guessing when a record is too thin.

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


# Tokens read for the FIRST time versus tokens pulled back OUT of the cache
# because a prior turn already read them. `usage_ledger.NEW_KEYS`/`REREAD_KEY`
# name the same split at the row level; this module cannot import a peer
# (`usage_ledger.py` sits one layer ABOVE this one, since it re-exports this
# module rather than the other way round), so the two field-name tuples are
# declared once each, at the layer that reads them, rather than shared.
_NEW_KEYS = ("in", "cacheW5m", "cacheW1h")


def context_shape(manifest, rows):
    """Per task: what was read for the first time, what was re-read out of
    cache, and the highest single-turn context any of its runs reached.

    Answers the question a plain cost total cannot — whether a task was
    expensive because it did a lot of NEW work or because it lived long
    enough to keep re-paying for context it had already read. The two have
    OPPOSITE repairs (narrow the task's scope; hand the remaining work to a
    fresh agent instead of continuing this one), so folding them into one
    number throws away the one thing an operator would act on.

    `newTokens`/`reReadTokens` are summed from fields every row this ledger
    has ever written carries (`in`/`cacheW5m`/`cacheW1h` versus `cacheR`), so
    they always have a basis — a task with recorded spend always has both.
    The per-turn peak does not: it is written only by a scanner new enough to
    have tracked it (see `usage_ledger.py`'s module docstring), so a task
    whose rows include even one written before that lands cannot support the
    claim. `contextBasis` says which case a caller is looking at, and
    `maxContext` is `None` rather than a number that would silently read as
    "this task's peak was small" — the rule this whole module already follows
    for a phase with no declared budget, applied here to a different gap."""
    tasks = task_index(manifest)
    out = {}
    for row in rows:
        tid = row.get("taskId")
        if not tid or tid not in tasks:
            continue
        slot = out.get(tid)
        if slot is None:
            slot = out[tid] = {"newTokens": 0, "reReadTokens": 0,
                               "maxContext": 0, "contextBasis": "measured"}
        for k in _NEW_KEYS:
            try:
                slot["newTokens"] += int(row.get(k) or 0)
            except (TypeError, ValueError):
                pass
        try:
            slot["reReadTokens"] += int(row.get("cacheR") or 0)
        except (TypeError, ValueError):
            pass
        if "maxContext" not in row:
            # ONE row missing the field is enough to void the peak for the
            # whole task: a max computed over only the rows that DO carry it
            # could silently be lower than the true peak, which is a wrong
            # answer dressed as a careful one. Never reversed below — once a
            # task's basis is voided for THIS call, no later row un-voids it.
            slot["contextBasis"] = "predates-tracking"
        elif slot["contextBasis"] != "predates-tracking":
            try:
                slot["maxContext"] = max(slot["maxContext"],
                                         int(row.get("maxContext") or 0))
            except (TypeError, ValueError):
                pass
    for slot in out.values():
        if slot["contextBasis"] == "predates-tracking":
            slot["maxContext"] = None
    return out


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


# --- what a gate caught, beside what it cost -------------------------------------
def gate_catches(tallies, floor):
    """Per gate name, what it caught paired with what it cost - never one
    without the other, because a figure about cost alone is the surface this
    function exists to fix.

    `tallies` is `{name: {"ran", "failed", "lastFailedAt", "costMs"}}`, folded
    by the CALLER from the evidence ledger's own tally
    (`_evidence_io.gate_tally`/`gate_names_seen`/`gate_last_caught`/
    `gate_cost_ms`) - the same reading `propose-gates.py` and
    `_doctor_trail.check_gate_patterns` already fold that ledger into. This
    module does not read the ledger itself: `_evidence_io` sits at this
    module's own layer, so a sideways read is not one this tree allows, and
    the counts arrive as arguments rather than being derived a third time.
    `floor` is the caller's own `_evidence_io.MIN_HISTORY_RUNS` for the same
    reason - carried in, never re-typed here.

    Sorted by name, and every entry carries all four caller-supplied fields
    plus a `verdict`:

      insufficient  `ran` is below `floor` - too short a history to support
                    either claim, stated rather than rounded either direction
      neverCaught   at or past `floor`, `failed` is zero - a real finding
                    about the gate, reported as such rather than a zero
                    averaged away
      catches       at or past `floor`, has failed at least once
    """
    out = []
    for name in sorted(tallies):
        entry = tallies[name] if isinstance(tallies.get(name), dict) else {}
        ran = entry.get("ran") or 0
        failed = entry.get("failed") or 0
        row = {"name": name, "ran": ran, "failed": failed,
               "lastFailedAt": entry.get("lastFailedAt"),
               "costMs": entry.get("costMs")}
        if ran < floor:
            row["verdict"] = "insufficient"
        elif failed == 0:
            row["verdict"] = "neverCaught"
        else:
            row["verdict"] = "catches"
        out.append(row)
    return out


# --- the plan's own cost, against the same work done without one ---------------
# THE CLAIM THE WHOLE PRODUCT RESTS ON, AND UNTIL THIS TASK NOTHING MEASURED IT.
# "Working through the plan costs less than working without one" is exactly the
# shape of claim this repo refuses everywhere else when nothing carries its
# basis - so the obvious shortcut is a single ratio, and a single ratio with no
# named subjects would be the most quotable number this product could print and
# the least checkable, because repeating it costs nothing and checking it costs
# re-deriving what it never named.
#
# Three comparisons are honest because a real PAIR of runs exists behind each
# one, not because they are convenient to compute:
#
#   * a task's own NARROWED gate against its PHASE's gate, on the SAME task -
#     `gate_scope_comparison`, reading `run-test-gate.py`'s own `gateSource`;
#   * a gate run that REUSED a verdict against the run it repeated -
#     `gate_reuse_comparison`, reading the same file's reuse identity;
#   * one completed task's spend against the spread of its SIBLING tasks' -
#     the other tasks its own phase ran - `sibling_spend_comparison`.
#
# EACH ANSWERS WITH NAMED SUBJECTS OR REFUSES, and the refusal is never a
# fallback to a default the way an absent phase budget or a thin cost-band
# sample already refuse elsewhere in this file. It is spelled with the word
# this tree already uses for an attempted comparison a record cannot support:
# `_refs.RED_FIRST_CANNOT` is that same spelling for a red-first proof that was
# attempted and refused for a reason that is not the work's; this is that word
# again for a comparison history is too thin to make, not a second convention
# invented beside it - which is why the string is defined here rather than
# imported, exactly as `_refs.py` itself defines `RED_FIRST_CANNOT` beside
# `run-test-gate.py`'s own `CANNOT_RUN` instead of importing it.
CANNOT_COMPARE = "could-not-prove"

# The per-phase sample floor `sibling_spend_comparison` uses - NOT a second
# number invented for this claim. It IS `MIN_TASKS_FOR_PROJECTION`, because the
# argument for suppressing a percentile below it is the same argument whether
# the pool being read is the whole project or one phase of it.
SIBLING_GATE = MIN_TASKS_FOR_PROJECTION


def gate_scope_comparison(evidence_rows):
    """One task's own narrowed gate against its phase's, on the SAME task.

    `run-test-gate.py` resolves a task's gate to exactly ONE scope by
    declaration - `gateSource` is `task` when the manifest's task carries a
    gate of its own, `phase` otherwise - so an ordinary run is recorded under
    whichever one the declaration picked, for the whole of that task's life.
    Seeing one recorded under BOTH scopes means an operator deliberately took
    the other path too (`--task` against a task with no gate of its own, or a
    bare phase run that also covers a task that has one): a real, occasional
    event, and this reads only occurrences of it rather than assuming every
    task must have taken both.

    Refuses with `CANNOT_COMPARE` when no task was ever measured both ways.
    `tasksRecorded` says how many tasks carry a gate run of EITHER scope, so a
    refusal here names how thin the history is rather than leaving a bare "no".
    """
    by_task = {}
    for row in (evidence_rows or []):
        if not isinstance(row, dict):
            continue
        tid = row.get("taskId")
        src = row.get("gateSource")
        dur = row.get("durationMs")
        if not tid or src not in ("task", "phase"):
            continue
        if isinstance(dur, bool) or not isinstance(dur, (int, float)):
            continue
        slot = by_task.setdefault(tid, {"task": [], "phase": []})
        slot[src].append(dur)

    both = [(tid, s) for tid, s in sorted(by_task.items())
            if s["task"] and s["phase"]]
    if not both:
        return {
            "verdict": CANNOT_COMPARE,
            "compares": "one task's own narrowed gate against its phase's gate",
            "reason": ("%d task(s) carry a recorded gate run and none of them "
                      "was ever measured under both scopes - an ordinary run "
                      "takes exactly one, so this needs a deliberate run this "
                      "history does not carry" % (len(by_task),)),
            "tasksRecorded": len(by_task),
        }
    tasks_out = []
    for tid, s in both:
        narrowed_ms = sum(s["task"]) / len(s["task"])
        phase_ms = sum(s["phase"]) / len(s["phase"])
        tasks_out.append({
            "taskId": tid,
            "narrowedRuns": len(s["task"]), "phaseRuns": len(s["phase"]),
            "narrowedMeanMs": round(narrowed_ms, 1),
            "phaseMeanMs": round(phase_ms, 1),
            "savedMs": round(phase_ms - narrowed_ms, 1),
        })
    return {"verdict": "compared",
            "compares": "one task's own narrowed gate against its phase's gate",
            "tasks": tasks_out}


def gate_reuse_comparison(evidence_rows):
    """A gate run that reused a verdict against the run it repeated.

    Grouped by `reuseKey`, `run-test-gate.py`'s own identity for "the same
    tree content, the same declared gate, the same declared files" (its
    `REUSE_LIMIT` states what the key does not establish). A key carrying both
    a `reused` row and a `measured` one is the pair this needs: the measured
    row is what running the gate again would have cost, and the reused row is
    what it actually cost - `durationMs` on a reused row is real wall time
    (computing the identity, printing the result), never zero, so the saving
    is READ off the two rather than asserted.

    Refuses with `CANNOT_COMPARE` when no key has both. `reusedRowsSeen` counts
    every row this history ever recorded with a reused verdict at all, so a
    refusal says whether the MECHANISM has ever fired, or only never lined up
    with a measured run sharing its identity.
    """
    by_key = {}
    for row in (evidence_rows or []):
        if not isinstance(row, dict):
            continue
        key = row.get("reuseKey")
        dur = row.get("durationMs")
        if not key or isinstance(dur, bool) or not isinstance(dur, (int, float)):
            continue
        slot = by_key.setdefault(key, {"reused": [], "measured": []})
        which = "reused" if row.get("verdictSource") == "reused" else "measured"
        slot[which].append({"runId": row.get("runId"),
                            "phaseId": row.get("phaseId"),
                            "taskId": row.get("taskId"), "durationMs": dur})

    reused_seen = sum(len(s["reused"]) for s in by_key.values())
    runs_out = []
    for key, s in sorted(by_key.items()):
        if not (s["reused"] and s["measured"]):
            continue
        taken_ms = sum(m["durationMs"] for m in s["measured"]) / len(s["measured"])
        for r in s["reused"]:
            runs_out.append({
                "reuseKey": key, "runId": r["runId"], "phaseId": r["phaseId"],
                "taskId": r["taskId"], "avoidedRunMs": round(r["durationMs"], 1),
                "measuredMeanMs": round(taken_ms, 1),
                "savedMs": round(taken_ms - r["durationMs"], 1),
            })
    if not runs_out:
        return {
            "verdict": CANNOT_COMPARE,
            "compares": ("a gate run that reused a verdict against the run it "
                        "repeated"),
            "reason": ("%d distinct gate identity group(s) are recorded in "
                      "this history, %d row(s) of which ever carried a reused "
                      "verdict at all, and none of those shares an identity "
                      "with a row this history actually measured"
                      % (len(by_key), reused_seen)),
            "reusedRowsSeen": reused_seen,
        }
    return {"verdict": "compared",
            "compares": "a gate run that reused a verdict against the run it repeated",
            "runs": runs_out}


def sibling_spend_comparison(manifest, rows):
    """One completed task's spend against the spread of its sibling tasks' -
    the other tasks its own phase ran, each its own agent's spend.

    Reuses the sample floor `cost_bands` already states (`SIBLING_GATE ==
    MIN_TASKS_FOR_PROJECTION`) rather than inventing a second number, scoped to
    ONE PHASE instead of the whole project: a percentile off a handful of
    tasks is noise wherever the pool it is drawn from. A phase short of the
    floor is named in `shortPhases` - carried on BOTH a `compared` and a
    `CANNOT_COMPARE` return, because a phase that fell short is excluded from
    `tasks` either way and a reader comparing two phases deserves to know one
    of them was never in the running rather than reading its absence as
    nothing to see. A task never appears in `tasks` unless its own phase
    cleared the floor.
    """
    tasks = task_index(manifest)
    cost_by_task, phase_by_task = {}, {}
    for row in (rows or []):
        tid = row.get("taskId")
        if not tid or tid not in tasks:
            continue
        cost_by_task[tid] = cost_by_task.get(tid, 0.0) + _cost(row)
        pid = row.get("phaseId")
        if pid and tid not in phase_by_task:
            phase_by_task[tid] = pid

    by_phase = {}
    for tid, cost in cost_by_task.items():
        if (tasks.get(tid) or {}).get("status") != "done":
            continue
        pid = phase_by_task.get(tid)
        if not pid:
            continue
        by_phase.setdefault(pid, []).append((tid, cost))

    tasks_out, short_phases = {}, []
    for pid, items in sorted(by_phase.items()):
        if len(items) < SIBLING_GATE:
            short_phases.append(pid)
            continue
        for tid, cost in items:
            siblings = [c for other, c in items if other != tid]
            tasks_out[tid] = {
                "phaseId": pid, "costUSD": round(cost, 4),
                "siblingCount": len(siblings),
                "siblingMedianUSD": round(_percentile(siblings, 50), 4),
                "siblingP25USD": round(_percentile(siblings, 25), 4),
                "siblingP75USD": round(_percentile(siblings, 75), 4),
            }
    if not tasks_out:
        # TWO DIFFERENT GAPS, ONE EMPTY RESULT - and the reason says which. An
        # `rows` with no cost attributable to ANY task never populates
        # `by_phase` at all, which is a different fact from a phase that DID
        # attribute cost but never reached the floor; folding the two into one
        # sentence would read "0 phase(s) fell short" over a history that
        # never had a phase to fall short WITH.
        if not by_phase:
            reason = ("no phase in this history has even one completed, "
                      "cost-attributed task to compare - there is no usage "
                      "ledger data here yet, only the plan")
        else:
            reason = ("%d phase(s) have completed, cost-attributed tasks and "
                      "none of them clears the sample floor cost bands "
                      "already uses" % (len(short_phases),))
        return {
            "verdict": CANNOT_COMPARE,
            "compares": ("one task's spend against the spend of its sibling "
                        "tasks in the same phase"),
            "reason": reason,
            "gate": SIBLING_GATE,
            "shortPhases": short_phases,
        }
    return {"verdict": "compared",
            "compares": ("one task's spend against the spend of its sibling "
                        "tasks in the same phase"),
            "gate": SIBLING_GATE,
            "tasks": tasks_out,
            # Named even on an answered call - a phase that fell short of the
            # floor is excluded from `tasks` silently otherwise, and a reader
            # comparing two phases deserves to know one of them was never in
            # the running rather than reading its absence as "nothing to see".
            "shortPhases": short_phases}


def plan_cost_claim(manifest, rows, evidence_rows):
    """The three honest comparisons behind "the plan costs less than working
    without one" - `_usage_economics.py`'s own module docstring lists them, and
    `plugins/audit/README.md`'s Token usage section is what an operator reads.

    Never a single ratio. A reader wanting ONE number from this has asked the
    wrong question, and the shape of this return says so before they can build
    one: three named comparisons, each independently `compared` or
    `CANNOT_COMPARE`, and no field here sums or averages them into an answer
    none of the three actually gave.
    """
    return {
        "gateScope": gate_scope_comparison(evidence_rows),
        "gateReuse": gate_reuse_comparison(evidence_rows),
        "siblingSpend": sibling_spend_comparison(manifest, rows),
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
