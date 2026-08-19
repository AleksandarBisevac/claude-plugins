#!/usr/bin/env python3
"""
Cost per completed task and mean attempts, per model, WITHIN a risk band - and
the only advice this repo's own evidence supports.

One of four passes cut out of `_usage_analytics.py` (U3.2) on its own
`# --- model routing ---` marker, every body moved by line range.

Deliberately NOT a spend-share / task-share ratio. Tasks are not equal-sized:
the plugin's own guidance routes hard work to the strong model on purpose and
warns that a cheap botched attempt costs more than one clean expensive pass, so
a bare ratio would show that working system as a problem and push users toward
exactly the routing the docs warn against. Comparing within a risk band is the
only comparison that means anything.

`_routing_advice` then adds four more conditions for the same reason: the
cheaper model must already have run `MIN_ROUTING_EVIDENCE` tasks in that band IN
THIS REPO, its mean attempts must be no worse than the incumbent's, both models
must have real rates rather than a `_default` guess, and the saving must clear
both a percentage and an absolute floor. Every one of them is there to stop this
becoming the glib advice the routing table was built to avoid.

Reads `_usage_core` and nothing else in the tree; `usage_ledger.py` re-exports
every public name defined here, so no call site names this module.

This module carries no `--selftest` of its own; its 14 cases live in
`plugins/audit/tests/test__usage_routing.py`, the moved labels byte-identical -
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
from _usage_core import (  # noqa: E402  (the rate table, and the plan index)
    DEFAULT_PRICING, TOKEN_KEYS, price, rates_for, task_index)

# Thin module-level aliases, not copies: the bodies below moved out of
# `_usage_analytics.py` by line range, and an alias keeps them reading the same
# names while there is still exactly ONE definition of each, one layer down.
_cost = _core._cost


# --- model routing --------------------------------------------------------------
RISK_ORDER = ("high", "med", "low", "unrated")


def routing(manifest, rows, pricing=None):
    """Cost per completed task and mean attempts, per model, WITHIN a risk band.

    Deliberately NOT a spend-share / task-share ratio. Tasks are not equal-sized —
    the plugin's own guidance routes hard work to the strong model on purpose and
    warns that a cheap botched attempt costs more than one clean expensive pass. A
    bare ratio would show that working system as a problem and push users toward
    exactly the routing the docs warn against. Comparing within a risk band is the
    only comparison that means anything.

    Models come from the LEDGER (what actually ran), never from the manifest's
    `model` field, which is a provider-agnostic tier name in a different namespace."""
    tasks = task_index(manifest)
    acc = {}
    for row in rows:
        tid = row.get("taskId")
        t = tasks.get(tid) if tid else None
        if not t:
            continue
        risk = t.get("risk") or "unrated"
        model = row.get("model") or "unknown"
        cell = acc.setdefault((risk, model),
                              {"cost": 0.0, "tasks": {},
                               "counts": {k: 0 for k in TOKEN_KEYS}})
        cell["cost"] += _cost(row)
        cell["tasks"][tid] = t
        # Kept so the counterfactual below can re-price the SAME tokens at another
        # model's rates. Cost alone cannot do that.
        for k in TOKEN_KEYS:
            cell["counts"][k] += int(row.get(k) or 0)
    by_risk, counts_by = {}, {}
    for (risk, model), cell in acc.items():
        n = len(cell["tasks"])
        attempts = [int(t.get("attempts") or 1) for t in cell["tasks"].values()]
        by_risk.setdefault(risk, {})[model] = {
            "tasks": n,
            "cost": round(cell["cost"], 4),
            "costPerTask": round(cell["cost"] / n, 4) if n else None,
            "meanAttempts": round(sum(attempts) / float(len(attempts)), 2)
            if attempts else None,
        }
        counts_by[(risk, model)] = cell["counts"]
    return {
        "byRisk": by_risk,
        "risks": [r for r in RISK_ORDER if r in by_risk],
        "models": sorted({m for cells in by_risk.values() for m in cells}),
        "advice": _routing_advice(by_risk, counts_by, pricing),
    }


MIN_ROUTING_EVIDENCE = 3    # tasks needed on BOTH models, in that band, in this repo
ATTEMPT_TOLERANCE = 0.2     # a cheaper model that retries more is not cheaper
MIN_ADVICE_SAVING_USD = 1.0
MIN_ADVICE_SAVING_PCT = 10.0


def _has_rates(model, pricing=None):
    """True only when the price table names this model. `rates_for` falls back to
    `_default` for anything unknown, and recommending a move onto a model whose
    price is a guess would be worse than saying nothing."""
    table = pricing if isinstance(pricing, dict) and pricing else DEFAULT_PRICING
    fallback = table.get("_default") or DEFAULT_PRICING["_default"]
    return rates_for(model, pricing) is not fallback


def _routing_advice(by_risk, counts_by, pricing=None):
    """Where the ledger's own evidence supports moving work to a cheaper model.

    Every condition here exists to stop this becoming the glib advice the routing
    table was built to avoid:

    * WITHIN one risk band only. The plugin routes hard work to the strong model
      on purpose; comparing across bands would flag that working system as a fault.
    * The cheaper model must already have run `MIN_ROUTING_EVIDENCE` tasks in that
      band IN THIS REPO. Without that, "sonnet would be cheaper" is a price-list
      observation, not a finding — of course it is cheaper, it is also different.
    * Its mean attempts must be no worse than the incumbent's (plus a small
      tolerance). A cheap model that retries twice is not cheaper, and
      `_usage_economics.retry_cost` says exactly that. (It read "the retry
      analytics right above this" until U3.2 put them in another file - a
      spatial reference is the first thing a split falsifies.)
    * Both models must have real rates in the table, never a `_default` guess.
    * The saving must clear both a percentage and an absolute floor, or the advice
      is noise dressed as insight.

    Both sides are priced at TODAY's rates on the same token counts, so the two
    numbers share one rate epoch — comparing a historical cost against a current
    price list would be a different (and wrong) sum. The result is an upper bound,
    not a forecast: a different model would not emit the same tokens.
    """
    out = []
    for risk, cells in by_risk.items():
        ranked = sorted(cells.items(), key=lambda kv: -(kv[1]["cost"]))
        for model, cell in ranked:
            if cell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(model, pricing):
                continue
            counts = counts_by.get((risk, model)) or {}
            at_from = price(counts, model, pricing)
            best = None
            for other, ocell in cells.items():
                if other == model:
                    continue
                if ocell["tasks"] < MIN_ROUTING_EVIDENCE or not _has_rates(other, pricing):
                    continue
                if (ocell["meanAttempts"] or 0) > (cell["meanAttempts"] or 0) \
                        + ATTEMPT_TOLERANCE:
                    continue
                at_other = price(counts, other, pricing)
                saving = at_from - at_other
                if saving < MIN_ADVICE_SAVING_USD:
                    continue
                if at_from <= 0 or 100.0 * saving / at_from < MIN_ADVICE_SAVING_PCT:
                    continue
                if best is None or saving > best[1]:
                    best = (other, saving, at_other, ocell)
            if best:
                other, _saving, at_other, ocell = best
                # Round FIRST, then derive — so the three figures reconcile on
                # screen. Rounding each independently let 25.01 - 15.00 print as a
                # saving of 10.00, which is a cent nobody can account for in a
                # module whose whole claim is that its numbers can be checked.
                af, at = round(at_from, 2), round(at_other, 2)
                out.append({
                    "risk": risk, "from": model, "to": other,
                    "tasks": cell["tasks"],
                    "fromMeanAttempts": cell["meanAttempts"],
                    "atFromRates": af,
                    "atToRates": at,
                    "saving": round(af - at, 2),
                    "savingPct": round(100.0 * (af - at) / af, 1) if af else 0.0,
                    "evidenceTasks": ocell["tasks"],
                    "evidenceAttempts": ocell["meanAttempts"],
                })
    out.sort(key=lambda a: -a["saving"])
    return out


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_routing.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_routing.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
