#!/usr/bin/env python3
"""
The cases for `_usage_routing.py` - cost per completed task per model WITHIN a
risk band, and the advice this repo's own evidence supports.

Written at U3.2, when `_usage_analytics.py` was cut on its own section markers.
These cases were the `routing` and `advice` groups of
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
import _usage_routing as M                         # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- a task whose attempts were zeroed while its spend stayed --------------
    # `attempts: 0` is not hypothetical: `audit-task.py` writes it for every new
    # task, and TWO documented paths reach it with ledger rows already attributed —
    # `orchestrator.md` reverts the increment after a specific failure ("revert the
    # attempts increment from step 2"), and `/audit:run` resets a blocked or
    # re-opened task to 0. In both, the manifest says zero and the ledger keeps the
    # tokens.
    #
    # `int(t.get("attempts") or 1)` therefore reports 1 for a task the manifest says
    # has none, and the arithmetic below is measured, not assumed: over a cell of one
    # zeroed task and one that ran twice, the mean is 1.5 where the recorded values
    # average 1.0.
    #
    # IT IS PINNED RATHER THAN CHANGED, deliberately. Zeroing attempts while keeping
    # spend is itself an inconsistency, and it inflates the COST side of the same
    # cell in the same direction — so `or 1` partly compensates rather than simply
    # lying, and `meanAttempts` feeds routing ADVICE. Flipping an advice number on a
    # judgement call is worse than recording the decision. This case is what makes
    # the next change to it deliberate: if somebody decides zero should read as
    # zero, this is the case they will have to edit, and the reasoning is here.
    _z_man = {"phases": [{"id": "PZ", "tasks": [
        {"id": "PZ.1", "status": "pending", "risk": "high", "attempts": 0},
        {"id": "PZ.2", "status": "done", "risk": "high", "attempts": 2}]}]}
    _z_rows = [{"taskId": "PZ.1", "model": "m", "in": 10, "out": 100,
                "cacheR": 1000, "cacheW5m": 100, "costUSD": 0.1},
               {"taskId": "PZ.2", "model": "m", "in": 10, "out": 100,
                "cacheR": 1000, "cacheW5m": 100, "costUSD": 0.1}]
    _z_cell = M.routing(_z_man, _z_rows)["byRisk"]["high"]["m"]
    check("za1 a zeroed task DOES reach the cell - it is joined by taskId from the "
          "ledger, not by status - so its attempts count is in the mean: %d task(s)"
          % (_z_cell["tasks"],), _z_cell["tasks"] == 2)
    check("za2 ...and the mean reads 1.5, where the recorded 0 and 2 average 1.0: "
          "`or 1` reports one attempt for a task the manifest says has none. Pinned, "
          "not fixed - see the note above - so a change here is a decision and not "
          "a drift (got %r)" % (_z_cell["meanAttempts"],),
          _z_cell["meanAttempts"] == 1.5)
    check("za3 THE PAIR: with only the spawned task in the ledger the mean is 2.0, "
          "so za2 is reading the zeroed task's contribution and not a constant",
          M.routing(_z_man, _z_rows[1:])["byRisk"]["high"]["m"]["meanAttempts"]
          == 2.0)

    def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
              cr=1000, cw=100, fin=10):
        return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                "taskId": task, "phaseId": phase, "attr": attr,
                "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                "cacheR": cr, "costUSD": cost}

    man = {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done", "risk": "high", "attempts": 1},
        {"id": "P1.2", "status": "done", "risk": "high", "attempts": 3},
        {"id": "P1.3", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.4", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.5", "status": "done", "risk": "med", "attempts": 1},
        {"id": "P1.6", "status": "blocked", "risk": "med", "attempts": 3},
        {"id": "P1.7", "status": "pending", "risk": "low"},
    ]}]}
    ar = [
        mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
        mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
        mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
        mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
        mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
        mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
        mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
    ]

    # routing advice: fires only when THIS repo's own evidence supports it.
    # Both fixtures above route one model per band, so neither produces advice
    # — a well-routed project getting silence is the point, not a gap.
    def band(model, n, attempts, out_tok, risk="low", first=0):
        man_tasks = [{"id": "R%s%d" % (model[7:10], i), "status": "done",
                      "risk": risk, "attempts": attempts} for i in range(n)]
        rws = [mkrow(1 + first, model, "a@x", t["id"], "PR", "task", 0.0,
                     out_tok=out_tok) for t in man_tasks]
        return man_tasks, rws

    o_t, o_r = band("claude-opus-5", 5, 1, 200_000)
    s_t, s_r = band("claude-sonnet-5", 4, 1, 200_000)
    rman = {"phases": [{"id": "PR", "tasks": o_t + s_t}]}
    adv = M.routing(rman, o_r + s_r)["advice"]
    check("advice: a within-band cheaper model with real evidence is named",
          len(adv) == 1 and adv[0]["from"] == "claude-opus-5"
          and adv[0]["to"] == "claude-sonnet-5" and adv[0]["risk"] == "low",
          adv)
    # The three figures must reconcile EXACTLY: a reader who subtracts the two
    # displayed costs has to land on the displayed saving, to the cent.
    check("advice: both sides priced on the SAME tokens at today's rates, and "
          "the arithmetic on screen adds up exactly",
          adv and adv[0]["atFromRates"] > adv[0]["atToRates"] > 0
          and adv[0]["saving"] == round(
              adv[0]["atFromRates"] - adv[0]["atToRates"], 2)
          and adv[0]["savingPct"] == round(
              100.0 * adv[0]["saving"] / adv[0]["atFromRates"], 1),
          adv)
    check("advice: it carries the in-repo evidence it rests on",
          adv and adv[0]["evidenceTasks"] == 4
          and adv[0]["evidenceAttempts"] == 1.0 and adv[0]["tasks"] == 5)

    # Each gate, alone, must silence it.
    s2_t, s2_r = band("claude-sonnet-5", 2, 1, 200_000)
    check("advice: SILENT when the cheaper model has too little in-repo "
          "evidence (a price list is not a finding)",
          M.routing({"phases": [{"id": "PR", "tasks": o_t + s2_t}]},
                  o_r + s2_r)["advice"] == [])
    s3_t, s3_r = band("claude-sonnet-5", 4, 2, 200_000)
    check("advice: SILENT when the cheaper model retries more — a model that "
          "needs two attempts is not cheaper",
          M.routing({"phases": [{"id": "PR", "tasks": o_t + s3_t}]},
                  o_r + s3_r)["advice"] == [])
    tiny_o, tiny_or = band("claude-opus-5", 5, 1, 100)
    tiny_s, tiny_sr = band("claude-sonnet-5", 4, 1, 100)
    check("advice: SILENT when the saving is below the absolute floor",
          M.routing({"phases": [{"id": "PR", "tasks": tiny_o + tiny_s}]},
                  tiny_or + tiny_sr)["advice"] == [])
    x_t, x_r = band("claude-mystery-9", 4, 1, 200_000)
    check("advice: SILENT for a model with no real rates — never recommend a "
          "move onto a price that is a _default guess",
          M._has_rates("claude-mystery-9") is False
          and M.routing({"phases": [{"id": "PR", "tasks": o_t + x_t}]},
                      o_r + x_r)["advice"] == [])
    # Cross-band comparison is the thing the whole table exists to refuse.
    hi_t, hi_r = band("claude-sonnet-5", 4, 1, 200_000, risk="high")
    check("advice: never compares ACROSS risk bands",
          all(a["risk"] == "low" for a in M.routing(
              {"phases": [{"id": "PR", "tasks": o_t + hi_t}]},
              o_r + hi_r)["advice"]))

    # routing: within-risk comparison, no bare ratio
    rt = M.routing(man, ar)
    check("routing: grouped by risk band, then model",
          "high" in rt["byRisk"] and "claude-opus-5" in rt["byRisk"]["high"])
    check("routing: exposes NO spend-share/task-share ratio",
          not any("ratio" in k.lower() for cells in rt["byRisk"].values()
                  for cell in cells.values() for k in cell))
    check("routing: carries cost-per-task and mean attempts per cell",
          rt["byRisk"]["high"]["claude-opus-5"]["costPerTask"] == 20.0
          and rt["byRisk"]["high"]["claude-opus-5"]["meanAttempts"] == 2.0)
    check("routing: models come from the LEDGER, not manifest tiers",
          all(m.startswith("claude-") for m in rt["models"]))
    check("routing: risks are ordered high -> low, not alphabetical",
          rt["risks"] == ["high", "med", "low"])

    # The alias, not a second definition - see test__usage_spend.py's note.
    import _usage_core as _core
    check("alias: _cost and task_index ARE _usage_core's, not same-named copies "
          "- the split moved them down a layer, so there is still exactly one "
          "definition of each",
          M._cost is _core._cost and M.task_index is _core.task_index)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_routing.py --selftest\n")
    raise SystemExit(2)
