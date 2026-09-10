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

import glob
import json
import os
import shutil
import subprocess
import tempfile
import io
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _locks                                      # noqa: E402  (held/refusal: the lock contract, read once)
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

    # ---- (ap) F296: add-phase's allocator returns highest-plus-one -----------
    # THE FIXTURE HAS A GAP IN IT, and that is the whole design of these cases:
    # over a plan with no gap the two rules answer identically, so a taken set
    # without one is a case that cannot go red under either allocator. `P2` is
    # missing here, `P3` is the highest, and the two rules therefore disagree by
    # construction.
    _ap_taken = {"P0", "P1", "P3", "P0.1", "P3.2", "BF9"}
    check("ap1 add-phase's allocator returns highest-plus-one over the shared "
          "taken set, and never RETURNS P0: a gap is a phase that HAPPENED, and "
          "`meta.branch` derives a branch name from the id, so re-minting one "
          "hands the caller a phase colliding with the branches and merges "
          "already carrying that number - measured live, `add-phase` returned "
          "P30 while `p30/*` named four branches and two merges: %r"
          % (M.next_appended_phase_id(_ap_taken),),
          M.next_appended_phase_id(_ap_taken) == "P4"
          and M.next_appended_phase_id(set()) == "P1"
          and M.next_appended_phase_id({"P0"}) == "P1")
    check("ap2 ...and MATERIALIZE keeps the lowest-free rule over the SAME set - "
          "the taken set is shared and only the rule forks, because that verb "
          "re-places a payload whose id collided with live work and the gap it "
          "drops into was never anybody's: %r"
          % (M.next_phase_id(_ap_taken),),
          M.next_phase_id(_ap_taken) == "P2"
          and M.next_appended_phase_id(_ap_taken)
          != M.next_phase_id(_ap_taken))
    check("ap3 ...and \"the highest\" means the highest that PARSES as `P<n>`: "
          "a taken set mixes shapes on purpose - this plan carries `BF1`/`BF2` "
          "between its P-ids, a task id is `P<n>.<m>` and a proposal reserves "
          "both - so `BF9` (its own sequence) and `P1.7` (a task) are ignored "
          "rather than counted, which would push the next phase past a number "
          "nobody typed: %r"
          % (M.next_appended_phase_id({"BF9", "P1", "P1.7"}),),
          M.next_appended_phase_id({"BF9", "P1", "P1.7"}) == "P2"
          # The real interleaving, off this repository's own plan shape.
          and M.next_appended_phase_id(
              {"P14", "BF1", "BF2", "P15", "PROP-3"}) == "P16")
    check("ap3b ...and a set with NO `P<n>` in it allocates P1 - the stated "
          "rule rather than a fallback that happens to work. An empty plan and "
          "a plan holding only `BF1` are the same answer, because the maximum "
          "is counted from a floor of zero and nothing special-cases the empty "
          "set. That is also why `P0` is never RETURNED, while an `--id P0` a "
          "caller names stays accepted: `examples/acme-store` ships a real P0 "
          "phase and the starter template opens with one: %r"
          % ([M.next_appended_phase_id(set()),
              M.next_appended_phase_id({"BF1", "BF2"}),
              M.next_appended_phase_id({"PROP-1"})],),
          M.next_appended_phase_id(set()) == "P1"
          and M.next_appended_phase_id({"BF1", "BF2"}) == "P1"
          and M.next_appended_phase_id({"PROP-1"}) == "P1"
          # Not a string, and a `P` with no number: neither counts and neither
          # raises - a taken set reaches this before anything has graded it.
          and M.next_appended_phase_id({None, 7, "P", "Pxx", "P3"}) == "P4")
    # SECOND-DIRECTION CASE for ap1. The wrong over-correction is a floor that
    # always fires: `max(...) + 1` clamped to some minimum above 1 would satisfy
    # every line above while refusing to continue a plan that really does sit at
    # P1, and a plan whose highest id is high must keep counting from there.
    check("ap4 SECOND-DIRECTION CASE: the P0 floor is a floor and not a clamp - "
          "a plan already at P41 allocates P42, so nothing here is being "
          "rounded up to a constant: %r"
          % (M.next_appended_phase_id({"P41"}),),
          M.next_appended_phase_id({"P41"}) == "P42"
          and M.next_appended_phase_id({"P1"}) == "P2")
    check("ap5 `commands/phase.md`'s `--id` paragraph is graded against both "
          "allocators rather than trusted: it carries a worked example (a plan, "
          "the id an append takes from it, the id the other rule would have "
          "taken) and this evaluates it - the sentence it replaced said the verb "
          "'continues the sequence', which described a rule the code did not "
          "have: %r" % (M.phase_id_doc_drift(),),
          M.phase_id_doc_drift() == [])
    # THE VACUITY GUARD for ap5, and it is not decoration: `== []` is also what
    # a check that stopped being able to FIND the sentence would return if the
    # missing-example branch were ever dropped, so a document with no example
    # has to be a finding here too.
    _ap_nodoc = tempfile.mkdtemp(prefix="audit-prop-doc-")
    try:
        os.makedirs(os.path.join(_ap_nodoc, "commands"))
        with io.open(os.path.join(_ap_nodoc, "commands", "phase.md"),
                     "w", encoding="utf-8") as fh:
            fh.write("- **`--id`** - omit it. The script continues the "
                     "`P<n>` sequence.\n")
        _ap_missing = M.phase_id_doc_drift(root=_ap_nodoc)
        check("ap6 ...a `--id` paragraph carrying an ADJECTIVE and no worked "
              "example is a finding, which is what stops ap5 from being green "
              "over a document it can no longer read: %r" % (_ap_missing,),
              len(_ap_missing) == 1 and "no worked example" in _ap_missing[0])
        with io.open(os.path.join(_ap_nodoc, "commands", "phase.md"),
                     "w", encoding="utf-8") as fh:
            fh.write("Over a plan holding `P0`, `P1` and `P3`, the next id is "
                     "`P2`, and never the `P4`.\n")
        _ap_swapped = M.phase_id_doc_drift(root=_ap_nodoc)
        check("ap7 ...and an example naming the two ids the OTHER way round - "
              "which is the document as it would read if the allocators were "
              "swapped back - reports both halves, so neither number is being "
              "read as decoration: %r" % (_ap_swapped,),
              len(_ap_swapped) == 2
              and any("allocates P2, and `next_appended_phase_id` allocates P4"
                      in p for p in _ap_swapped)
              and any("contrasts P4" in p and "takes P2" in p
                      for p in _ap_swapped))
        with io.open(os.path.join(_ap_nodoc, "commands", "phase.md"),
                     "w", encoding="utf-8") as fh:
            fh.write("Over a plan holding `P0` and `P1`, the next id is `P2`, "
                     "and never the `P2`.\n")
        _ap_flat = M.phase_id_doc_drift(root=_ap_nodoc)
        check("ap8 ...and an example over a plan with NO GAP is a finding even "
              "though both ids in it are right, because the two rules answer it "
              "identically: an example the allocators cannot be told apart on "
              "grades neither of them: %r" % (_ap_flat,),
              len(_ap_flat) == 1 and "cannot be told apart" in _ap_flat[0])
    finally:
        shutil.rmtree(_ap_nodoc, ignore_errors=True)

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

    # ---- the list view: ONE derivation, two surfaces ----
    # `proposal_rows` is what the panel's Proposals tab paints as cards AND what
    # `/audit:propose list` prints as a table. It lived in `_panel_composition`
    # while the panel was the only surface that HAD a list - the command was
    # specified in prose and rendered by a model, so there was nothing to share
    # with. There is now, and a second walk is where two surfaces start answering
    # differently about one manifest.
    m10 = _manifest([_prop("PROP-1", payload=_payload("P5", tasks=("a", "b")),
                           openQuestions=["ship it?"]),
                     _prop("PROP-2", payload=None),
                     _prop("PROP-3", "materialized", _payload("P1"),
                           materializedAs="P1"),
                     _prop("PROP-4", "dropped", _payload("P8"), notes="dupe"),
                     _prop("PROP-5", "open", payload=None)],
                    phases=[{"id": "P1", "tasks": []}])
    rows = dict((r["id"], r) for r in M.proposal_rows(m10))
    check("mz28 a payload-bearing row carries the phase it RESERVES and the task "
          "count that comes with it - the list table's third column is made of "
          "exactly those two fields: %r" % (rows.get("PROP-1"),),
          rows["PROP-1"]["phaseId"] == "P5"
          and rows["PROP-1"]["taskCount"] == 2
          and rows["PROP-1"]["hasPayload"] is True)
    check("mz29 ...while a legacy free-form entry reports no payload rather than "
          "a phase of its own, which is what makes the `-` columns a fact and not "
          "a rendering accident: %r" % (rows.get("PROP-2"),),
          rows["PROP-2"]["hasPayload"] is False
          and rows["PROP-2"]["phaseId"] is None
          and rows["PROP-2"]["taskCount"] == 0)

    m11 = _manifest([_prop("PROP-1", payload=_payload("P5")),
                     _prop("PROP-2",
                           payload=_payload("P6", refs=["P5", "P0", "P404"]))],
                    phases=[{"id": "P0", "tasks": []}])
    row2 = [r for r in M.proposal_rows(m11) if r["id"] == "PROP-2"][0]
    direct = [ref for ref, _owner in M.unresolved_refs(
        m11["proposals"][1]["payload"]["phase"], m11, skip=("PROP-2",))]
    check("mz30 `waitsOn` is `unresolved_refs`' own answer rather than a second "
          "walk beside it, and the edge to the LIVE P0 is dropped - a fixture "
          "whose refs were all unresolved could not tell a filter from a "
          "passthrough: %r vs %r" % (row2["waitsOn"], direct),
          row2["waitsOn"] == direct and direct == ["P5", "P404"])

    view = M.list_view(m10)
    shown = [r["id"] for r in view["rows"]]
    check("mz31 the default list is everything still OPEN - the parked ones AND "
          "the hand-written status the vocabulary does not know, which is the "
          "entry a `status == proposed` filter would make invisible on the one "
          "surface that reads proposals in full: %r" % (shown,),
          shown == ["PROP-1", "PROP-2", "PROP-5"])
    every = [r["id"] for r in M.list_view(m10, include_all=True)["rows"]]
    check("mz32 ...and `all` ADDS the materialized/dropped history rather than "
          "replacing the list: %r" % (every,),
          every == ["PROP-1", "PROP-2", "PROP-3", "PROP-4", "PROP-5"])
    check("mz33 ...and the view carries the basis an empty render needs: how many "
          "records the default filter hid, and whether there is a plan at all: %r"
          % (dict((k, v) for k, v in view.items() if k != "rows"),),
          view["hidden"] == 2 and view["total"] == 5 and view["phaseCount"] == 1)
    empty = M.list_view(_manifest([]))
    check("mz34 an empty manifest reports its phases as none, so a caller can "
          "tell 'nothing parked' from 'no plan to park anything in' - the two "
          "read alike and need different advice",
          empty["rows"] == [] and empty["phaseCount"] == 0
          and empty["hidden"] == 0 and empty["total"] == 0)

    # ---- the status a row carries, and the one it was WRITTEN with (F93) ----
    # A row normalises a MISSING status to `proposed` so a badge has something
    # to paint. `/audit:status` classifies by the RAW one, because an entry
    # carrying no status is exactly what its legacy footer exists to report and
    # a normalisation would move it into the parked list instead. Both readings
    # ride one row; these are the cases that keep them apart.
    vocab = _manifest([_prop("PROP-1"),                       # proposed
                       _prop("PROP-2", "materialized"),
                       _prop("PROP-3", "dropped"),
                       _prop("PROP-4", "open"),               # out of vocabulary
                       _prop("PROP-5", None)])                # none at all
    by_id = dict((r["id"], r) for r in M.proposal_rows(vocab))
    check("mz35 an entry with NO status displays as `proposed` and SAYS the "
          "value it was written with was none - a surface that only got the "
          "display value could not tell it from a real parked one: %r"
          % ({k: (v["status"], v["statusRaw"]) for k, v in by_id.items()},),
          by_id["PROP-5"]["status"] == "proposed"
          and by_id["PROP-5"]["statusRaw"] is None
          and by_id["PROP-1"]["statusRaw"] == "proposed")
    check("mz36 `statusKnown` is read off the plugin's OWN vocabulary, so a "
          "word added to `PROPOSAL_STATUS` is known here without this file "
          "learning it: %r"
          % ({k: v["statusKnown"] for k, v in by_id.items()},),
          [by_id[k]["statusKnown"] for k in
           ("PROP-1", "PROP-2", "PROP-3", "PROP-4", "PROP-5")]
          == [True, True, True, False, False])
    check("mz37 the default list filter and the vocabulary are the same table "
          "seen from two sides - HISTORY_STATUS plus `proposed` IS "
          "PROPOSAL_STATUS, so a fourth word cannot be added to the vocabulary "
          "and silently stay outside what `list` hides: %r vs %r"
          % (sorted(set(M.HISTORY_STATUS) | set(["proposed"])),
             sorted(M._vocab.PROPOSAL_STATUS)),
          set(M.HISTORY_STATUS) | set(["proposed"])
          == set(M._vocab.PROPOSAL_STATUS))

    # ---- the reserved cell, which three surfaces print (F93) ----
    cell = _manifest([_prop("PROP-1", payload=_payload("P4", tasks=("a", "b"))),
                      _prop("PROP-2", payload=_payload("P5", tasks=("a",))),
                      _prop("PROP-3")])
    rows_c = dict((r["id"], r) for r in M.proposal_rows(cell))
    check("mz38 the cell agrees the noun with the count, and says `-` when "
          "there is no payload to reserve anything: %r"
          % ([M.reserved_cell(rows_c[k])
              for k in ("PROP-1", "PROP-2", "PROP-3")],),
          [M.reserved_cell(rows_c[k]) for k in
           ("PROP-1", "PROP-2", "PROP-3")] == ["P4 (2 tasks)", "P5 (1 task)",
                                               "-"])
    # A payload whose `tasks` list holds something that is not a task object:
    # counting the LIST gives one answer and counting the task OBJECTS another,
    # and the two surfaces used to give one each. The fixture exists so the two
    # implementations cannot agree by accident.
    malformed = _manifest([_prop("PROP-1", payload=_payload("P4",
                                                            tasks=("a",)))])
    malformed["proposals"][0]["payload"]["phase"]["tasks"].append("not a task")
    row_m = M.proposal_rows(malformed)[0]
    check("mz39 a payload carrying a malformed task counts the task OBJECTS, "
          "not the length of the list - the number a reader uses to decide "
          "whether a materialization is small: %r"
          % (M.reserved_cell(row_m),),
          row_m["taskCount"] == 1 and M.reserved_cell(row_m) == "P4 (1 task)")
    check("mz40 a row with no payload never reaches `phaseId` - `hasPayload` "
          "is the basis, so a legacy entry cannot be printed as reserving a "
          "phase that does not exist",
          M.reserved_cell({"hasPayload": False, "phaseId": "P9",
                           "taskCount": 3}) == "-")

    # --- F188: the lock is a STATUS CODE, and both things done with it were wrong
    # `_locks.acquire` returns an int on every path. This module named it `handle`
    # and tested it with `isinstance(..., dict)`, which is never true of an int -
    # so the release in the `finally` never ran and every write left the index lock
    # on disk, and the code was never read, so a refused acquire fell into the
    # write and changed the manifest with NO LOCK HELD.
    #
    # BOTH CASES COUNT THE LOCK FILE AND THE BYTES, never the return value: `run()`
    # already answered `True` while the lock leaked, so a case built on its answer
    # is the case that was there.
    _lk_tmp = tempfile.mkdtemp(prefix="audit-prop-lock-")
    try:
        subprocess.call(["git", "init", "-q", _lk_tmp])
        os.makedirs(os.path.join(_lk_tmp, "docs", "audit"))
        _lk_mp = os.path.join(_lk_tmp, "docs", "audit", "audit-plan.json")

        def _lk_write():
            with io.open(_lk_mp, "w", encoding="utf-8") as fh:
                json.dump(_manifest([_prop("PROP-1", payload=_payload("P9"))]), fh)

        def _lk_files():
            return sorted(os.path.basename(x) for x in
                          glob.glob(os.path.join(_lk_tmp, ".git",
                                                 "audit-locks", "*")))
        _lk_write()
        _ok, _info = M.run(_lk_mp, "materialize", ["PROP-1"])
        check("lk1 a SUCCESSFUL materialize leaves no lock behind - counted on "
              "disk, because `run()` returned True while the lock leaked and a "
              "case reading that answer would have passed: %r"
              % (_lk_files(),),
              _ok and _lk_files() == [])

        _lk_write()
        _lk_before = io.open(_lk_mp, "rb").read()
        _real = _locks.acquire
        _locks.acquire = lambda *_a, **_k: _locks.E_LIVE
        try:
            _ok2, _info2 = M.run(_lk_mp, "materialize", ["PROP-1"])
        finally:
            _locks.acquire = _real
        check("lk2 ...and a REFUSED acquire writes nothing - the manifest is byte "
              "identical, which is the assertion, since the old code returned True "
              "here after writing with no lock at all: %r"
              % ((_ok2, _info2),),
              _ok2 is False
              and io.open(_lk_mp, "rb").read() == _lk_before)
        check("lk3 ...and the refusal is `_locks`' own sentence, carrying NO host "
              "and no absolute path - `acquire`'s terminal lines name the machine "
              "a live pid runs on, and this payload is painted by the panel: %r"
              % ((_info2 or {}).get("findings"),),
              (_info2 or {}).get("findings")
              == [_locks.refusal(_locks.E_LIVE, M.LOCK_NAME)]
              and "pid " not in _locks.refusal(_locks.E_LIVE, M.LOCK_NAME)
              and os.sep not in _locks.refusal(_locks.E_LIVE, M.LOCK_NAME))
        # THE THIRD ANSWER, and leaving it out re-broke the panel. `acquire` says
        # `E_ERR` both for "not a git repository" - no lock to take, and never was
        # - and for a real failure, so refusing on every non-zero code refused
        # every write in a project with no `.git`. The panel has a documented
        # fallback for exactly that case. Caught by the browser gate, not here,
        # which is why the case exists now.
        _ng = tempfile.mkdtemp(prefix="audit-prop-nogit-")
        try:
            os.makedirs(os.path.join(_ng, "docs", "audit"))
            _ng_mp = os.path.join(_ng, "docs", "audit", "audit-plan.json")
            with io.open(_ng_mp, "w", encoding="utf-8") as fh:
                json.dump(_manifest([_prop("PROP-1",
                                           payload=_payload("P9"))]), fh)
            _ng_ok, _ng_info = M.run(_ng_mp, "materialize", ["PROP-1"])
            check("lk5 a project with NO lock scheme still writes - `available()` "
                  "is asked before acquiring, where the answer is unambiguous, "
                  "rather than inferred from a code that means two things: %r"
                  % ((_ng_ok, (_ng_info or {}).get("message")),),
                  _locks.available(_ng) is False and _ng_ok is True)
        finally:
            shutil.rmtree(_ng, ignore_errors=True)
    finally:
        shutil.rmtree(_lk_tmp, ignore_errors=True)



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__proposals.py --selftest\n")
    raise SystemExit(2)
