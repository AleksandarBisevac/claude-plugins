#!/usr/bin/env python3
"""
A timer over the analytics passes, and the fixture it times them on.

This is the sixth piece of `_usage_analytics.py` (U3.2) and the only one that is
not a `rows -> dict` pass, which is why it does not carry the name: it CALLS the
four modules the analytics were cut into, so it sits one layer above them, at
layer 3 beside `usage_ledger`. Nothing imports it - `render-report.py` reaches
`_time_best` through `_loader` so that the two benches in this tree share one
definition of best-of-N, and `--bench` is run by a human.

The section comment below carries the argument for every choice here (why it
exists at all, why it is not a CI threshold, why best-of-N rather than the mean,
and why it opens no file). It moved with the code and is the thing to read
before changing any of it.

This module carries no `--selftest` of its own; its 10 cases live in
`plugins/audit/tests/test__usage_bench.py`, the moved labels byte-identical - see
`plugins/audit/tests/_harness.py`. `--bench` stayed: the benchmark is production
code somebody runs, and only the `bn` cases ABOUT it moved.
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

from _usage_core import aggregate  # noqa: E402  (the hottest thing a report runs)
from _usage_coverage import coverage, monthly_activity  # noqa: E402
from _usage_economics import (  # noqa: E402
    cost_bands, phase_budgets, retry_cost, unit_economics)
from _usage_routing import routing  # noqa: E402
from _usage_spend import cache_profile, compare, series  # noqa: E402


# --- bench ----------------------------------------------------------------------
# WHY THIS EXISTS. Several comments in this tree state a measured cost — the
# `aggregate` this module imports carries "Measured 30.0 ms -> 18.4 ms over 20,000
# rows", `hooks/meter-usage.py` says "26 ms over a 9-month, 8,740-row ledger" — and
# until now there was not one `perf_counter`, `timeit` or benchmark anywhere in the
# repository, so not one of those numbers could be produced again by anybody,
# including their author. This is the smallest honest repair: a fixture, a timer,
# and a figure a human can run twice and compare.
#
# DELIBERATELY NOT A CI THRESHOLD. A shared runner's noise floor is wider than the
# regressions worth catching, and a gate that flaps teaches people to ignore it —
# which costs more than having no gate. This prints; it never fails.
#
# BEST-OF-N, NOT THE MEAN. Timing noise on a shared machine is ONE-SIDED: every
# other thing running can only make a call slower, never faster. A mean therefore
# reports the machine's mood alongside the code, while the minimum is the closest
# observable thing to the true cost. `_time_best` returns the minimum and every
# printed figure carries the run count, because a minimum without its sample size
# is not a measurement.
#
# NO I/O, EVER. The fixture is COMPUTED, not read. This module opens no file (see
# the module docstring) and the bench keeps it that way, so nothing here can read —
# or grow — the repo's own live `.claude/usage/` ledger.

_BENCH_SIZES = (1000, 10000, 50000)
_BENCH_REPEATS = 5
_BENCH_PHASES = 12
_BENCH_TASKS = 12
_BENCH_MONTHS = 9
_BENCH_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")
_BENCH_AUTHORS = ("alex@bench.example", "sara@bench.example", "milos@bench.example")
_BENCH_RISKS = ("high", "med", "low")

# `_report_usage.load_usage` calls `aggregate` six times per report (day, phase,
# model, author, agent, session). COUNTED at those call sites, not remembered:
# `_usage_core.aggregate`'s own comment still says eleven, which was the count
# BEFORE those calls were hoisted out of the payload dict. Six is what a report
# costs today, so six is what the derived line below multiplies by.
_BENCH_AGGREGATE_PER_REPORT = 6


def _time_best(fn, repeats, clock=None):
    """`(seconds, result)` — the FASTEST of `repeats` calls, and the last result.

    The minimum, never the mean; the section comment above says why. `clock` is
    injectable for one reason: a timing harness whose clock cannot be replaced can
    only be tested by sleeping, and a case that asserts "the minimum, not the
    mean" against real sleeps is a case that flakes on a busy machine. The
    selftest hands it a scripted clock and pins the answer exactly.
    """
    clock = clock if clock is not None else time.perf_counter
    best, out = None, None
    for _ in range(max(1, int(repeats))):
        start = clock()
        out = fn()
        elapsed = clock() - start
        if best is None or elapsed < best:
            best = elapsed
    return best, out


def _bench_manifest():
    """The fixed plan the fixture's rows are attributed to.

    The PLAN is fixed while the row count varies, because that is the shape a
    ledger actually grows in: a manifest is written once and metered against for
    months. Every honesty gate in this module is cleared ON PURPOSE — enough done
    tasks for the projection and the cost bands, budgets on some phases and not
    others, all three risk bands, retried tasks and blocked ones, bugs with a
    linked task. A fixture that tripped a gate would have the bench timing a guard
    clause and printing it as the cost of the function.
    """
    phases = []
    for p in range(1, _BENCH_PHASES + 1):
        tasks = []
        for t in range(1, _BENCH_TASKS + 1):
            i = (p - 1) * _BENCH_TASKS + (t - 1)
            status = "done"
            if i % 7 == 0:
                status = "blocked" if i % 14 == 0 else "pending"
            tasks.append({
                "id": "P%d.%d" % (p, t), "title": "bench task %d" % i,
                "status": status, "risk": _BENCH_RISKS[i % 3],
                "attempts": 3 if i % 9 == 0 else 1,
                "completedAt": "2026-%02d-%02dT10:00:00Z" % (1 + i % _BENCH_MONTHS,
                                                            1 + i % 28),
            })
        phase = {"id": "P%d" % p, "title": "bench phase %d" % p, "status": "done",
                 "mergedAt": "2026-%02d-05T10:00:00Z" % (1 + p % _BENCH_MONTHS),
                 "tasks": tasks}
        if p % 3 == 0:                       # some budgeted, some not
            phase["budgetUSD"] = 50.0
        phases.append(phase)
    bugs = [{"id": "BUG-%d" % b, "status": "open",
             "severity": "med",
             "reportedAt": "2026-%02d-1%dT10:00:00Z" % (1 + b % _BENCH_MONTHS,
                                                        b % 10),
             "taskId": "P%d.2" % (1 + b % _BENCH_PHASES)}
            for b in range(1, 13)]
    return {"meta": {}, "phases": phases, "bugs": bugs}


def _bench_rows(n):
    """`n` deterministic ledger rows for `_bench_manifest()`'s plan.

    Deterministic by ARITHMETIC rather than by a seeded RNG, so the fixture is
    identical on every interpreter and `_bench_rows(n)[:m] == _bench_rows(m)` —
    which is what makes the per-row figures at 1k, 10k and 50k comparable to each
    other rather than three unrelated samples.

    Shaped like the real thing: hour buckets across `_BENCH_MONTHS` months, three
    models, three authors, a rotating session id, and roughly one row in eleven
    left unattributed so `coverage` has both sides to divide.
    """
    tids = ["P%d.%d" % (p, t) for p in range(1, _BENCH_PHASES + 1)
            for t in range(1, _BENCH_TASKS + 1)]
    span = _BENCH_MONTHS * 28              # 28-day months: every date is real
    rows = []
    for i in range(n):
        day = i % span
        tid = tids[i % len(tids)]
        adhoc = (i % 11 == 0)
        rows.append({
            "ts": "2026-%02d-%02dT%02d" % (1 + day // 28, 1 + day % 28, i % 24),
            "model": _BENCH_MODELS[i % len(_BENCH_MODELS)],
            "author": _BENCH_AUTHORS[i % len(_BENCH_AUTHORS)],
            "sessionId": "sess-%d" % (i % 40),
            "agentType": None if adhoc else "audit-executor",
            "phaseId": None if adhoc else tid.split(".")[0],
            "taskId": None if adhoc else tid,
            "attr": "unattributed" if adhoc else "task",
            "msgs": 1 + i % 5,
            "in": 100 + i % 900,
            "out": 500 + i % 4000,
            "cacheW5m": 1000 + i % 9000,
            "cacheW1h": i % 500,
            "cacheR": 20000 + i % 60000,
            "costUSD": 0.10 + (i % 97) / 100.0,
        })
    return rows


# The comparison window `compare` is timed over: the middle third of the fixture's
# own span, so both the current and the prior window hold rows. A window with an
# empty prior returns early and would time nothing.
_BENCH_SINCE = "2026-04-01"
_BENCH_UNTIL = "2026-06-28"


def _bench_cases(manifest, rows):
    """`(label, thunk)` per timed case — every rows -> dict pass this module
    defines, plus `aggregate`, which is defined one layer down but is the hottest
    thing a report runs through this layer.

    Two properties the `bn` cases below hold this to:

    * the fixture is built OUTSIDE the thunk and closed over, so the timer measures
      the call and never the fixture build;
    * every LABEL is the name of the function its thunk calls. That pairing is
      proven by swapping the named global out and watching the thunk go through it,
      because a label that drifted onto its neighbour is worse than no bench: it
      reports the wrong function's cost under the right function's name, and is
      believed.

    `task_index` and `band_of` are absent on purpose — the first runs INSIDE four
    of the cases below, the second is a dict lookup.
    """
    return (
        ("aggregate", lambda: aggregate(rows, "day")),
        ("series", lambda: series(rows, "model")),
        ("compare", lambda: compare(rows, _BENCH_SINCE, _BENCH_UNTIL)),
        ("cache_profile", lambda: cache_profile(rows)),
        ("unit_economics", lambda: unit_economics(manifest, rows)),
        ("cost_bands", lambda: cost_bands(manifest, rows)),
        ("phase_budgets", lambda: phase_budgets(manifest, rows)),
        ("retry_cost", lambda: retry_cost(manifest, rows)),
        ("routing", lambda: routing(manifest, rows)),
        ("coverage", lambda: coverage(rows)),
        ("monthly_activity", lambda: monthly_activity(manifest, rows)),
    )


def _bench(sizes=None, repeats=None):
    """Print the analytics pass's wall time at several ledger sizes. Always 0.

    Several sizes rather than one number, because the interesting property is the
    SHAPE: a pass that is 1 us/row at 1,000 rows and 1 us/row at 50,000 rows is
    linear and needs nothing, while one whose per-row cost climbs is quadratic and
    will meet a ledger it cannot finish.
    """
    sizes = sizes if sizes is not None else _BENCH_SIZES
    repeats = repeats if repeats is not None else _BENCH_REPEATS
    manifest = _bench_manifest()
    # The one line of the moved block that could NOT come across byte for byte:
    # it printed `_usage_analytics`, and after U3.2 no such file exists. A header
    # naming a module that is not there is the kind of quiet lie this file's own
    # section comment argues against.
    #
    # A LITERAL, not `__name__`, and that was measured rather than assumed: run
    # as a command - which is the ONLY way `--bench` is ever reached - `__name__`
    # is `"__main__"`, so the derived form printed `__main__ --bench` and traded
    # one wrong name for another. `bn9` compares this literal against the
    # module's real `__name__` under import, so a rename that forgets it fails.
    print("_usage_bench --bench  (python %s on %s)"
          % (sys.version.split()[0], sys.platform))
    print("fixture:  %d phases x %d tasks = %d tasks, %d months, computed in "
          "memory - this module opens no file, so no ledger on this machine is "
          "read or written"
          % (_BENCH_PHASES, _BENCH_TASKS, _BENCH_PHASES * _BENCH_TASKS,
             _BENCH_MONTHS))
    print("timing:   best of %d runs per case - the MINIMUM, not the mean, "
          "because other load can only make a call slower" % repeats)
    print("note:     aggregate() is timed on the 'day' dimension; load_usage() "
          "calls it %d times per report" % _BENCH_AGGREGATE_PER_REPORT)
    for n in sizes:
        rows = _bench_rows(n)
        print("")
        print("rows=%s" % "{:,}".format(len(rows)))
        print("  %-18s %10s %11s" % ("case", "best", "per row"))
        total, agg = 0.0, None
        for label, thunk in _bench_cases(manifest, rows):
            seconds, _ = _time_best(thunk, repeats)
            total += seconds
            if label == "aggregate":
                agg = seconds
            print("  %-18s %7.3f ms %8.3f us"
                  % (label, seconds * 1e3, seconds * 1e6 / max(1, n)))
        # A SUM of minima, not a measured whole-pass time - said so rather than
        # printed as if one run had been observed taking it.
        print("  %-18s %7.3f ms %8.3f us"
              % ("sum of minima", total * 1e3, total * 1e6 / max(1, n)))
        if agg is not None:
            print("  %-18s %7.3f ms %8.3f us"
                  % ("aggregate x%d" % _BENCH_AGGREGATE_PER_REPORT,
                     agg * _BENCH_AGGREGATE_PER_REPORT * 1e3,
                     agg * _BENCH_AGGREGATE_PER_REPORT * 1e6 / max(1, n)))
    return 0


def _mode(argv):
    """Which mode the flags ask for: 'selftest', 'bench' or 'usage'.

    `--selftest` WINS over `--bench` when both are given. CI runs `--selftest` on
    every `.py` in the tree on two platforms; a suite that could turn into a
    multi-second benchmark run because a stray flag came along would be paid for
    on every push. A mode that can be entered by accident will be.
    """
    if "--selftest" in argv:
        return "selftest"
    if "--bench" in argv:
        return "bench"
    return "usage"



if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    _MODE = _mode(sys.argv[1:])
    if _MODE == "selftest":
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one. `--bench` still runs the
        # benchmark: that is production code, not a suite, and only the cases
        # ABOUT it moved.
        print("_usage_bench.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_bench.py - run that file "
              "instead. --bench still works here.")
        raise SystemExit(0)
    if _MODE == "bench":
        raise SystemExit(_bench())
    sys.stderr.write("usage: _usage_bench.py --selftest | --bench\n")
    raise SystemExit(2)
