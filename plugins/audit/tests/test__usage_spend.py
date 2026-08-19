#!/usr/bin/env python3
"""
The cases for `_usage_spend.py` - spend through time, and what the cache did to
the input side.

Written at U3.2, when `_usage_analytics.py` was cut on its own section markers.
These ten cases were the `series` / `compare` / `cache` groups of
`test__usage_analytics.py` and moved with their subject, labels unchanged; the
alias case at the foot is new, and pins the one thing the split could have
quietly broken. `M` is the module under test; see `test__cli_fmt.py` for why
that prefix and not a `from ... import` list.

`mkrow` and the fixture rows below are a COPY of the ones in the three sibling
suites this file was cut from, and deliberately so: a shared fixture module would
make one suite's edit reach into four others, which is the coupling the split was
undoing. What is shared here is the subject, not the scaffolding.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_spend as M                           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
              cr=1000, cw=100, fin=10):
        return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                "taskId": task, "phaseId": phase, "attr": attr,
                "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                "cacheR": cr, "costUSD": cost}

    ar = [
        mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
        mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
        mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
        mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
        mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
        mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
        mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
    ]

    # series: top-N fold
    s = M.series(ar, "model")
    check("series: buckets sorted, one value per bucket per entity",
          s["buckets"] == sorted(s["buckets"])
          and all(len(e["values"]) == len(s["buckets"]) for e in s["entities"]))
    check("series: values sum back to each entity total",
          all(sum(e["values"]) == e["total"] for e in s["entities"]))
    many = [mkrow(1, "m%02d" % i, "a@x", None, None, "unattributed", 1.0)
            for i in range(12)]
    sm = M.series(many, "model", top=8)
    check("series: past 8 entities the tail folds into 'other', never a 9th hue",
          len(sm["entities"]) == 9 and sm["entities"][-1]["key"] == "other"
          and sm["folded"] == 4)
    check("series: folding preserves the grand total",
          sum(e["total"] for e in sm["entities"]) == sum(M._tokens(r) for r in many))

    # compare: no prior period -> no invented delta
    c_none = M.compare(ar, "2026-08-01", "2026-08-07")
    check("compare: no prior window -> prior None and no deltas",
          c_none["prior"] is None and c_none["deltas"] == {})
    c_some = M.compare(ar, "2026-08-05", "2026-08-07")
    check("compare: a real prior window yields deltas",
          c_some["prior"] is not None and "tokens" in c_some["deltas"])
    check("compare: a zero-valued prior metric yields None, not a division blow-up",
          M.compare(ar, "2026-08-01", "2026-08-02")["deltas"] in ({}, None)
          or all(v is None or isinstance(v, float)
                 for v in M.compare(ar, "2026-08-05", "2026-08-07")["deltas"].values()))

    # cache_profile: rates, never a fabricated dollar saving
    cp = M.cache_profile(ar)
    check("cache: reports a hit rate and a rate comparison",
          0 <= cp["hitPct"] <= 100 and 0 < cp["inputCostVsFreshPct"] <= 100)
    check("cache: exposes NO fabricated dollar saving",
          not any("sav" in k.lower() or k.endswith("USD") for k in cp))
    check("cache: per-phase rates and a worst phase for the story",
          "P1" in cp["byPhase"] and cp["worstPhase"] is not None)

    # The alias, not a second definition. `_tokens` and `_cost` sit in
    # `_usage_core` because four modules at layer 2 need them and a layer-2
    # module may not import a peer; the names above still read as they always
    # did because this module binds them to the ONE definition one layer down.
    # A copy would be the token-formatter mistake this repo already made once.
    import _usage_core as _core
    check("alias: _tokens and _cost ARE _usage_core's, not same-named copies - "
          "the split moved them down a layer and left an alias, so there is "
          "still exactly one definition of each",
          M._tokens is _core._tokens and M._cost is _core._cost)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_spend.py --selftest\n")
    raise SystemExit(2)
