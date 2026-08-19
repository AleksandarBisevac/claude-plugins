#!/usr/bin/env python3
"""
Spend through time, and what the cache did to the input side: `series`,
`compare`, `cache_profile`.

One of four passes cut out of `_usage_analytics.py` (U3.2) when it reached 955
lines. The cut follows that file's own `# --- spend over time ---` marker and
every body moved by line range rather than being retyped, so this module does
exactly what that section did.

The honesty rules stated at each function are the point rather than decoration.
A first-run dashboard has nothing to compare against and must not invent a
"+100%", so `compare` returns None for the prior window and every delta.
`cache_profile` reports RATES and never a dollar saving: without caching you
would not have made the same calls at the same volume, so that number is a
fabricated counterfactual. `series` folds its tail past `MAX_SERIES` because the
categorical palette is only validated to eight slots - a correctness bound, not
a style preference.

Reads `_usage_core` and nothing else in the tree, which is what keeps it at
layer 2 beside its three sibling passes; `usage_ledger.py` re-exports every
public name defined here, so no call site names this module.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_spend.py`, the moved labels byte-identical - see
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

import _usage_core as _core  # noqa: E402  (the arithmetic under every pass here)
from _usage_core import (  # noqa: E402  (roll-ups, buckets, the rate table)
    GROUP_KEYS, TOKEN_KEYS, bucket_date, parse_ts, rates_for, totals)

# Thin module-level aliases, not copies: the bodies below moved out of
# `_usage_analytics.py` by line range, and an alias keeps them reading the same
# names while there is still exactly ONE definition of each, one layer down.
_tokens = _core._tokens
_cost = _core._cost

MAX_SERIES = 8              # categorical hue cap; past this the tail folds


# --- spend over time ------------------------------------------------------------
def series(rows, dim, bucket="day", top=MAX_SERIES, metric="tokens"):
    """Time series per entity, ready for a multi-line chart.

    Past `top` entities the tail folds into a single `other` entry rather than
    generating a 9th hue nothing can distinguish — the categorical palette is only
    validated to 8 slots, so this is a correctness bound, not a style preference.

    Returns {buckets, entities:[{key, values, total}], folded, metric}.
    """
    keyfn = GROUP_KEYS[dim]
    valfn = _tokens if metric == "tokens" else _cost
    per = {}
    seen_buckets = set()
    for row in rows:
        b = bucket_date(row.get("ts")) if bucket == "day" else (row.get("ts") or "")
        if not b:
            continue
        seen_buckets.add(b)
        k = keyfn(row)
        per.setdefault(k, {})
        per[k][b] = per[k].get(b, 0) + valfn(row)
    buckets = sorted(seen_buckets)
    ranked = sorted(per.items(), key=lambda kv: -sum(kv[1].values()))
    keep, tail = ranked[:top], ranked[top:]
    entities = [{"key": k, "total": sum(v.values()),
                 "values": [v.get(b, 0) for b in buckets]} for k, v in keep]
    if tail:
        merged = {}
        for _, v in tail:
            for b, n in v.items():
                merged[b] = merged.get(b, 0) + n
        entities.append({"key": "other", "total": sum(merged.values()),
                         "values": [merged.get(b, 0) for b in buckets]})
    return {"buckets": buckets, "entities": entities, "folded": len(tail),
            "metric": metric}


def compare(rows, since, until):
    """This window vs the one immediately before it, same length.

    Returns None for `prior` and every delta when there is nothing to compare
    against — a first-run dashboard must not invent a '+100%'."""
    start, end = parse_ts((since or "") + "T00:00:00Z"), \
        parse_ts((until or "") + "T23:59:59Z")
    current = [r for r in rows
               if (not since or bucket_date(r.get("ts")) >= since)
               and (not until or bucket_date(r.get("ts")) <= until)]
    out = {"current": totals(current), "prior": None, "deltas": {}, "window": None}
    if start is None or end is None or end <= start:
        return out
    span = end - start
    p_start, p_end = start - span, start
    prior = []
    for r in rows:
        t = parse_ts((bucket_date(r.get("ts")) or "") + "T00:00:00Z")
        if t is not None and p_start <= t < p_end:
            prior.append(r)
    if not prior:
        return out
    pt = totals(prior)
    out["prior"] = pt
    for key in ("tokens", "costUSD", "msgs", "out"):
        before = pt.get(key) or 0
        now = out["current"].get(key) or 0
        out["deltas"][key] = (100.0 * (now - before) / before) if before else None
    out["window"] = {"since": since, "until": until}
    return out


def cache_profile(rows):
    """Cache economics, stated as RATES rather than an invented saving.

    Deliberately returns no "you saved $N": without caching you would not have made
    the same calls at the same volume, so that number is a fabricated counterfactual.
    `inputCostVsFreshPct` is a real rate comparison — what the input side actually
    bills as a share of what the identical token volume would bill at fresh-input
    rates — and is safe to show."""
    slot = {k: 0 for k in TOKEN_KEYS}
    per_phase = {}
    for row in rows:
        for k in TOKEN_KEYS:
            slot[k] += int(row.get(k) or 0)
        pid = row.get("phaseId") or "--"
        p = per_phase.setdefault(pid, {k: 0 for k in TOKEN_KEYS})
        for k in TOKEN_KEYS:
            p[k] += int(row.get(k) or 0)

    def hit(d):
        billed = d["in"] + d["cacheW5m"] + d["cacheW1h"] + d["cacheR"]
        return (100.0 * d["cacheR"] / billed) if billed else 0.0

    by_phase = {pid: round(hit(d), 1) for pid, d in per_phase.items()}
    worst = min(by_phase.items(), key=lambda kv: kv[1]) if by_phase else None
    # Rate comparison against the fresh-input price of the SAME volume.
    actual = fresh = 0.0
    for row in rows:
        r = rates_for(row.get("model"))
        vol = (int(row.get("in") or 0) + int(row.get("cacheW5m") or 0)
               + int(row.get("cacheW1h") or 0) + int(row.get("cacheR") or 0))
        actual += (int(row.get("in") or 0) * r["in"]
                   + int(row.get("cacheW5m") or 0) * r["cacheW5m"]
                   + int(row.get("cacheW1h") or 0) * r["cacheW1h"]
                   + int(row.get("cacheR") or 0) * r["cacheR"])
        fresh += vol * r["in"]
    return {
        "hitPct": round(hit(slot), 1),
        "readTokens": slot["cacheR"],
        "writeTokens": slot["cacheW5m"] + slot["cacheW1h"],
        "freshTokens": slot["in"],
        "inputCostVsFreshPct": round(100.0 * actual / fresh, 1) if fresh else 100.0,
        "byPhase": by_phase,
        "worstPhase": worst,
    }


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_spend.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_spend.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
