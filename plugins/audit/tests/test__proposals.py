#!/usr/bin/env python3
"""
The cases for `_proposals.py` — what materialize, drop and revive MEAN.

Split from `test_materialize_proposal.py` when the code split: that file now tests
a DOOR (arguments, exit codes) and this one tests the rule behind it. Keeping both
in one suite would have been the same conflation the modules were split to undo.

WHAT IS PINNED, and why each one is here rather than trusted:

- **Every refusal, in `propose.md`'s own order.** Unknown id, already
  materialized, dropped, and legacy free-form with nothing to move. The dropped
  branch must QUOTE the reason: a refusal that says "it was dropped" and not why
  sends the reader to the JSON.
- **The dependency closure, dependency-first.** Materializing a phase whose
  blocker is still parked writes a manifest the validator refuses, so the blocker
  goes first. A cycle must terminate rather than recurse - the validator reports
  the cycle, and a diagnostic must not hang on one.
- **Undecided is refused, not guessed.** That is what lets a caller ask a human and
  come back with the answer, and why the decision is a parameter rather than an
  interview inside a rule an HTTP endpoint has to call.
- **The collision guard remaps INSIDE the payload only.** An edge to a live phase
  still means that live phase; rewriting it would silently repoint real work.
- **Drop needs a reason and revive keeps it.** An archive that cannot say why is a
  tombstone, and a revived proposal that forgot it was ever declined has lost the
  only thing the archive was for.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _proposals as M                             # noqa: E402

NOW = "2026-08-21T12:00:00Z"


def _payload(pid, tasks=("a",), refs=None):
    """A parked payload phase, with optional blockedBy refs on the phase."""
    phase = {"id": pid, "title": "Parked " + pid, "status": "pending",
             "tasks": [{"id": "%s.%d" % (pid, i + 1), "title": t,
                        "status": "pending", "files": ["src/%s.py" % t]}
                       for i, t in enumerate(tasks)]}
    if refs:
        phase["blockedBy"] = list(refs)
    return {"phase": phase}


def _prop(pid, status="proposed", payload=None, **extra):
    out = {"id": pid, "name": "n " + pid, "status": status,
           "origin": "audit:init", "createdISO": "2026-01-01T00:00:00Z",
           "scope": "s", "benefit": "b", "openQuestions": [],
           "payload": payload}
    out.update(extra)
    return out


def _manifest(props, phases=None):
    return {"meta": {"version": 2, "project": "p", "gitRoot": "."},
            "phases": list(phases or []), "bugs": [], "fileIndex": {},
            "proposals": list(props)}



# --- cases ---------------------------------------------------------------------
def _cases(check):
    # ---- refusals, in propose.md's own order ----
    m = _manifest([_prop("PROP-1", payload=_payload("P9"))])
    check("mz1 an unknown id is refused by name",
          "no proposal PROP-7" in (M.refusal(M.find_proposal(m, "PROP-7"),
                                             "PROP-7") or ""))
    m2 = _manifest([_prop("PROP-1", "materialized", _payload("P1"),
                          materializedAs="P1")])
    why = M.refusal(M.find_proposal(m2, "PROP-1"), "PROP-1")
    check("mz2 an already-materialized proposal is refused and POINTS at its "
          "phase: %r" % (why,), "already materialized as P1" in (why or ""))
    m3 = _manifest([_prop("PROP-1", "dropped", _payload("P9"),
                          notes="duplicate of PROP-4")])
    why = M.refusal(M.find_proposal(m3, "PROP-1"), "PROP-1")
    check("mz3 a dropped proposal is refused and QUOTES the reason - a refusal "
          "that will not say why sends the reader to the JSON: %r" % (why,),
          "duplicate of PROP-4" in (why or ""))
    m4 = _manifest([_prop("PROP-1", payload=None)])
    why = M.refusal(M.find_proposal(m4, "PROP-1"), "PROP-1")
    check("mz4 a legacy free-form entry has nothing to materialize and says so",
          "no payload.phase" in (why or ""))
    check("mz5 ...while a payload-bearing proposed entry is NOT refused, so the "
          "checks above are about state and not about refusing everything",
          M.refusal(M.find_proposal(m, "PROP-1"), "PROP-1") is None)

    # ---- id allocation counts live AND parked ----
    m5 = _manifest([_prop("PROP-1", payload=_payload("P5")),
                    _prop("PROP-2", payload=_payload("P6"))],
                   phases=[{"id": "P0", "tasks": []}, {"id": "P1", "tasks": []}])
    taken = M.live_ids(m5) | M.parked_ids(m5)
    check("mz6 allocation counts parked reservations, not just live phases, so a "
          "second materialization cannot mint over the first: %s"
          % (sorted(taken),), M.next_phase_id(taken) == "P2")
    check("mz7 ...and a proposal stops reserving against ITSELF, or it could "
          "never keep its own id",
          "P5" not in M.parked_ids(m5, skip=("PROP-1",)))

    # ---- collision guard: remap inside the payload only ----
    live = _payload("P1", tasks=("x", "y"))["phase"]
    live["tasks"][1]["blockedBy"] = ["P1.1", "P0"]
    moved, mapping = M.remap_payload(live, "P7")
    check("mz8 a colliding payload is remapped: phase and task ids move together",
          moved["id"] == "P7" and moved["tasks"][0]["id"] == "P7.1", mapping)
    check("mz9 ...intra-payload refs follow the remap",
          moved["tasks"][1]["blockedBy"][0] == "P7.1")
    check("mz10 ...but an edge to a LIVE phase is left alone - rewriting it would "
          "silently repoint real work", moved["tasks"][1]["blockedBy"][1] == "P0")

    # ---- dependency closure ----
    m6 = _manifest([_prop("PROP-1", payload=_payload("P5")),
                    _prop("PROP-2", payload=_payload("P6", refs=["P5"]))])
    order = M.closure(m6, "PROP-2")
    check("mz11 the closure is dependency-FIRST: materializing PROP-2 puts its "
          "still-parked blocker PROP-1 ahead of it, because the other order "
          "writes a manifest the validator refuses: %s" % (order,),
          order == ["PROP-1", "PROP-2"])
    cyc = _manifest([_prop("PROP-1", payload=_payload("P5", refs=["P6"])),
                     _prop("PROP-2", payload=_payload("P6", refs=["P5"]))])
    check("mz12 a cycle terminates instead of recursing - the validator reports "
          "the cycle, and this must not hang on one",
          len(M.closure(cyc, "PROP-1")) == 2)

    # ---- undecided is refused, never guessed ----
    plan = M.plan_for(m6, ["PROP-2"])
    check("mz13 a single materialize that waits on a parked proposal reports it "
          "as a DECISION rather than resolving it: %s" % (plan["pulledIn"],),
          plan["needsDecision"] and plan["pulledIn"] == ["PROP-1"])
    plan2 = M.plan_for(m6, ["PROP-2"], policy="with-deps")
    check("mz14 ...and stops being a decision once the caller has stated one",
          not plan2["needsDecision"])
    lone = M.plan_for(_manifest([_prop("PROP-1", payload=_payload("P5"))]),
                      ["PROP-1"])
    check("mz15 ...while a payload that waits on nothing never asks",
          not lone["needsDecision"] and lone["steps"][0]["phaseId"] == "P5")

    # ---- the write ----
    m7 = _manifest([_prop("PROP-1", payload=_payload("P5", tasks=("a", "b")))])
    out, report = M.apply_materialize(m7, M.plan_for(m7, ["PROP-1"]), NOW)
    check("mz16 the phase lands in phases[] with its tasks",
          [p["id"] for p in out["phases"]] == ["P5"]
          and len(out["phases"][0]["tasks"]) == 2, report)
    check("mz17 ...fileIndex gains every task file, keyed by file to task ids",
          out["fileIndex"].get("src/a.py") == ["P5.1"], out["fileIndex"])
    prop = M.find_proposal(out, "PROP-1")
    check("mz18 ...and the proposal is flipped, not removed: materialized "
          "proposals are history like closed bugs",
          prop["status"] == "materialized" and prop["materializedAs"] == "P5"
          and prop["materializedAt"] == NOW)

    # ---- drop / revive ----
    m8 = _manifest([_prop("PROP-1", payload=_payload("P5"))])
    bad, msg = M.apply_drop(m8, "PROP-1", "   ", NOW)
    check("mz19 a drop with a blank reason is refused: an archive that cannot "
          "say why is a tombstone", bad is None and "needs a reason" in msg)
    ok, msg = M.apply_drop(m8, "PROP-1", "duplicate of PROP-4", NOW)
    check("mz20 ...with one it archives, keeping the payload",
          ok is not None
          and M.find_proposal(ok, "PROP-1")["status"] == "dropped"
          and M.find_proposal(ok, "PROP-1")["droppedAt"] == NOW
          and M.find_proposal(ok, "PROP-1")["payload"] is not None)
    m9 = _manifest([_prop("PROP-1", "materialized", _payload("P1"),
                          materializedAs="P1")])
    bad, msg = M.apply_drop(m9, "PROP-1", "changed my mind", NOW)
    check("mz21 a materialized proposal cannot be dropped - its phase is live "
          "and the record is the history trail",
          bad is None and "orphan the history trail" in msg)
    revived, msg = M.apply_revive(ok, "PROP-1")
    check("mz22 revive puts it back in play and KEEPS why it was declined - a "
          "revived proposal that forgot is an archive that lost its point",
          M.find_proposal(revived, "PROP-1")["status"] == "proposed"
          and "duplicate of PROP-4" in M.find_proposal(revived, "PROP-1")["notes"]
          and M.find_proposal(revived, "PROP-1")["droppedAt"] is None)
    bad, msg = M.apply_revive(revived, "PROP-1")
    check("mz23 ...and only a DROPPED proposal can be revived",
          bad is None and "not dropped" in msg)



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__proposals.py --selftest\n")
    raise SystemExit(2)
