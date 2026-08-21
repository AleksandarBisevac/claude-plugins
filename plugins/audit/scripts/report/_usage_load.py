#!/usr/bin/env python3
"""
Everything the Usage section plots, read straight from the ledger.

Split out of `_report_usage.py`. This is the only piece of that file that
touches a file at all - the other four take the dict this returns and give back
strings - which is the house rule about pushing I/O to the edges, applied to the
one section that had a read buried in the middle of its renderers.

Deliberately NOT taken from `audit-status.rollup`: the rollup is printed into a
model's context by /audit:status, so the bulky series (day x hour heatmap, daily
trend, phase x model cross-tab) are computed here in Python instead of being
carried through a JSON payload nobody reads.

Returns None when there is no ledger, and the section then renders as nothing at
all - which is the honest answer rather than an empty frame drawn to a scale
nobody measured.

THE COMPARISON WINDOW IS ANCHORED TO THE LEDGER'S OWN LAST DAY, not to the wall
clock, so a committed example report is byte-stable across re-renders and a
stale price table does not rot into a warning on its own.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_load.py` - see `plugins/audit/tests/_harness.py`.
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

import _loader  # noqa: E402  (the one way scripts/ loads a sibling script)
import _report_html  # noqa: E402  (the task index, aliased rather than re-walked)


# --- the small derivations the load needs --------------------------------------
def _iso_day(epoch):
    g = time.gmtime(epoch)
    return "%04d-%02d-%02dT00:00:00Z" % (g.tm_year, g.tm_mon, g.tm_mday)


def _pricing_stale(as_of, until, max_days=90):
    """True when the price table predates the newest ledger day by more than
    `max_days`. A silently stale rate is worse than no rate — every cost figure in
    the report is derived from it, so the report has to say when it cannot be
    trusted. Compared against the LEDGER's last day, not the wall clock, so a
    committed example does not rot into a warning on its own."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
        t_as_of = ul.parse_ts((as_of or "") + "T00:00:00Z")
        t_until = ul.parse_ts((until or "") + "T00:00:00Z")
        if t_as_of is None or t_until is None:
            return False
        return (t_until - t_as_of) > max_days * 86400
    except Exception:
        return False


def _hourly(rows, ul):
    """rows -> {"YYYY-MM-DD": [24 ints]} — tokens per hour per calendar date.

    The ledger already keys rows by hour bucket (`YYYY-MM-DDTHH`), so this is a
    straight regrouping, not a new derivation. Days appear only when they carry
    at least one parseable row; absent days are absent keys, and the client
    treats a missing day as 24 zeros."""
    out = {}
    for row in rows:
        bucket = row.get("ts")
        day = ul.bucket_date(bucket)
        hour = ul.bucket_hour(bucket)
        if not day or hour is None:
            continue
        vec = out.get(day)
        if vec is None:
            vec = out[day] = [0] * 24
        vec[hour] += sum(int(row.get(k) or 0) for k in ul.TOKEN_KEYS)
    return out


# --- the load ------------------------------------------------------------------
def load_usage(manifest, manifest_path, project_dir=None):
    """Everything the Usage section plots, read straight from the ledger.

    Deliberately NOT taken from `audit-status.rollup`: the rollup is printed into a
    model's context by /audit:status, so the bulky series (day x hour heatmap,
    daily trend, phase x model cross-tab) are computed here in Python instead of
    being carried through a JSON payload nobody reads. Returns None when there is
    no ledger — the section then renders as nothing at all."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    if not isinstance(meta_usage, dict):
        meta_usage = {}
    rel = meta_usage.get("ledgerDir") or os.path.join(".claude", "usage")
    ledger_dir = ul.find_ledger_dir(
        manifest_path, rel,
        project_dir or os.environ.get("CLAUDE_PROJECT_DIR"))
    if not ledger_dir:
        return None

    try:
        rows = ul.read_ledger(ledger_dir)
        if not rows:
            return None

        # One pass per dimension, hoisted. `aggregate` walks EVERY ledger row and
        # this dict asked for the same four dimensions more than once: `day` three
        # times (the token, cost and message series are three reads of one
        # aggregate) and phase/model/author twice each — once for the breakdown,
        # once for the orientation counts. Eleven full scans for six answers.
        # Sharing the dicts is safe because nothing here mutates one: `slim` builds
        # new dicts and the counts only measure key sets.
        by_day = ul.aggregate(rows, "day")
        by_phase = ul.aggregate(rows, "phase")
        by_model = ul.aggregate(rows, "model")
        by_author = ul.aggregate(rows, "author")

        def slim(agg):
            """The three fields a breakdown renders, out of a finished aggregate."""
            return {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                        "msgs": v["msgs"]}
                    for k, v in agg.items()}

        # Who the LEDGER recorded working on each task, strongest first.
        #
        # This is the only per-task identity the plugin actually has. The manifest
        # carries no assignee, and `_report_html._detail_row` says why inventing
        # one there would be wrong - it would be a claim the file does not make.
        # A metered turn, though, records BOTH its author and its taskId, so this
        # answers "who did this" with evidence instead of with a field somebody
        # was supposed to remember to fill in.
        #
        # Ordered by spend rather than alphabetically: on a task two people
        # touched, the one who did most of it is the one to ask first.
        task_spend = {}
        for r in rows:
            tid = r.get("taskId")
            who = r.get("author")
            if not tid or not who:
                continue
            n = sum(int(r.get(k) or 0) for k in ul.TOKEN_KEYS)
            task_spend.setdefault(tid, {})
            task_spend[tid][who] = task_spend[tid].get(who, 0) + n
        task_authors = {}
        for tid, spend in task_spend.items():
            ranked = sorted(spend.items(), key=lambda kv: (-kv[1], kv[0]))
            task_authors[tid] = [who for who, _ in ranked]

        phase_model = {}
        for r in rows:
            pid = r.get("phaseId") or "--"
            model = r.get("model") or "unknown"
            n = sum(int(r.get(k) or 0) for k in ul.TOKEN_KEYS)
            phase_model.setdefault(pid, {})
            phase_model[pid][model] = phase_model[pid].get(model, 0) + n

        titles = {}
        for ph in ((manifest or {}).get("phases") or []):
            if isinstance(ph, dict) and ph.get("id"):
                titles[ph["id"]] = ph.get("title") or ""

        # Comparison window is anchored to the LEDGER's own last day, not the wall
        # clock, so a committed example report is byte-stable across re-renders.
        days = sorted({ul.bucket_date(r.get("ts")) for r in rows} - {""})
        until = days[-1] if days else None
        since = None
        if until:
            t = ul.parse_ts(until + "T00:00:00Z")
            since = ul.hour_bucket(_iso_day(t - 29 * 86400))[:10] if t else None

        return {
            "totals": ul.totals(rows),
            "byPhase": slim(by_phase),
            "byModel": slim(by_model),
            "byAuthor": slim(by_author),
            "byAgent": slim(ul.aggregate(rows, "agent")),
            "phaseModel": phase_model,
            "taskAuthors": task_authors,
            "phaseTitles": titles,
            # Through `_report_html._tasks_by_id`, which IS `_manifest_io`'s
            # index (aliased, not copied — a case in that file pins the identity).
            # Same truthy-id filter and same LAST-wins duplicate rule this
            # comprehension had, so a duplicated task id still labels rows with
            # the last title the plan gives it.
            "taskTitles": {tid: t.get("title") or ""
                           for tid, t in
                           _report_html._tasks_by_id(manifest).items()},
            "daily": {k: v["tokens"] for k, v in by_day.items()
                      if k != "unknown"},
            "dailyCost": {k: v["costUSD"] for k, v in by_day.items()
                          if k != "unknown"},
            "dailyMsgs": {k: v["msgs"] for k, v in by_day.items()
                          if k != "unknown"},
            # Per-date hour vectors (C1/C3): {"YYYY-MM-DD": [24 ints]}. The 7x24
            # heatmap aggregates AWAY the calendar, so it cannot be navigated by
            # day/week/month/year after the fact — this keeps the calendar. It is
            # embedded into the page (see _usage_payload) for the report's own
            # date-range and heatmap navigation, both of which run client-side in
            # a file with no server to ask.
            "hourly": _hourly(rows, ul),
            "heatmap": ul.heatmap(rows),
            # the analytics layer — every one of these carries its own honesty guard
            "compare": ul.compare(rows, since, until) if since else None,
            "compareWindow": {"since": since, "until": until},
            "cache": ul.cache_profile(rows),
            "unit": ul.unit_economics(manifest, rows),
            "bands": ul.cost_bands(manifest, rows, meta_usage),
            "budgets": ul.phase_budgets(manifest, rows),
            "retry": ul.retry_cost(manifest, rows),
            "routing": ul.routing(manifest, rows, meta_usage.get("pricing")),
            "coverage": ul.coverage(rows),
            "monthly": ul.monthly_activity(manifest, rows),
            "seriesAuthorModel": {
                a: ul.series([r for r in rows if (r.get("author") or "unknown") == a],
                             "model")
                for a in sorted({r.get("author") or "unknown" for r in rows})},
            "showCost": bool(meta_usage.get("showCost", True)),
            "pricingAsOf": meta_usage.get("pricingAsOf"),
            "pricingStale": _pricing_stale(meta_usage.get("pricingAsOf"), until),
            # Orientation, not metrics. These answer "how big is the thing I am
            # looking at" — a question the tiles cannot answer, and one that would
            # cost five more tiles to answer badly.
            "counts": {
                "phases": len([k for k in by_phase if k != "--"]),
                "people": len(by_author),
                "models": len(by_model),
                "sessions": len([k for k in ul.aggregate(rows, "session")
                                 if k != "unknown"]),
                "days": len(days),
                "from": days[0] if days else None,
                "to": until,
            },
        }
    except Exception:
        return None

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
        print("_usage_load.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_load.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
