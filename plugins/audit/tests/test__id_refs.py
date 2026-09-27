#!/usr/bin/env python3
"""
The cases for `_id_refs.py` - one id renamed everywhere the plan points at it.

The fixture carries every field the schema says can hold another record's id, each
exactly once, so a field the renamer forgets shows up as the one old id still in the
output. `movedFrom` carries it too, and must keep it: that field is history.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _id_refs as M                               # noqa: E402


def _plan():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "a", "blockedBy": ["P2-abc"],
             "tasks": [{"id": "P1.1", "title": "t", "dependsOn": ["P2-abc.1"],
                        "blockedBy": ["P2-abc.1"], "bugId": "BUG-3-abc",
                        "movedFrom": {"id": "P2-abc.9", "phase": "P2-abc", "at": "x"}}]},
            {"id": "P2-abc", "title": "b",
             "tasks": [{"id": "P2-abc.1", "title": "u"}]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1", "P2-abc.1"]},
        "bugs": [{"id": "BUG-3-abc", "title": "b", "taskId": "P1.1"}],
        "proposals": [{"id": "PROP-1", "status": "materialized", "materializedAs": "P2-abc",
                       "payload": {"phase": {"id": "P2-abc", "title": "b"}}},
                      {"id": "PROP-2", "status": "proposed",
                       "payload": {"phase": {"id": "P9", "title": "c", "blockedBy": ["P2-abc"],
                                             "tasks": [{"id": "P9.1", "title": "v",
                                                        "dependsOn": ["P2-abc.1"]}]}}}],
    }


def _cases(check):
    plan = _plan()
    before = json.dumps(plan, sort_keys=True)
    mapping = M.phase_mapping(plan["phases"][1], "P7")
    check("ir1 a phase's mapping carries the phase AND each of its tasks, prefix swapped "
          "(the suffix placeholder's tasks become the real phase's)",
          mapping == {"P2-abc": "P7", "P2-abc.1": "P7.1"}, mapping)
    out, n = M.rename(plan, dict(mapping, **{"BUG-3-abc": "BUG-8"}))
    text = json.dumps(out, sort_keys=True)
    check("ir2 renamed everywhere: no old id survives anywhere but movedFrom",
          text.count('"P2-abc"') == 1 and text.count('"P2-abc.1"') == 0
          and '"BUG-3-abc"' not in text, text)
    check("ir3 ...the phase and task ids themselves",
          out["phases"][1]["id"] == "P7" and out["phases"][1]["tasks"][0]["id"] == "P7.1")
    t = out["phases"][0]["tasks"][0]
    check("ir4 ...blockedBy on phases and tasks, and dependsOn",
          out["phases"][0]["blockedBy"] == ["P7"] and t["blockedBy"] == ["P7.1"]
          and t["dependsOn"] == ["P7.1"])
    check("ir5 ...the reciprocal bug links, both ends",
          t["bugId"] == "BUG-8" and out["bugs"][0]["id"] == "BUG-8"
          and out["bugs"][0]["taskId"] == "P1.1")
    check("ir6 ...fileIndex values, in place, order kept",
          out["fileIndex"]["src/a.ts"] == ["P1.1", "P7.1"], out["fileIndex"])
    check("ir7 ...materializedAs, and every reference inside another proposal's payload",
          out["proposals"][0]["materializedAs"] == "P7"
          and out["proposals"][1]["payload"]["phase"]["blockedBy"] == ["P7"]
          and out["proposals"][1]["payload"]["phase"]["tasks"][0]["dependsOn"] == ["P7.1"])
    check("ir8 movedFrom is HISTORY and keeps the id the task was moved from",
          t["movedFrom"] == {"id": "P2-abc.9", "phase": "P2-abc", "at": "x"})
    check("ir9 the count is every rewritten occurrence, so a caller can say what it did",
          n == 12, n)
    check("ir10 the input is not mutated", json.dumps(plan, sort_keys=True) == before)
    same, zero = M.rename(copy.deepcopy(plan), {})
    check("ir11 an empty mapping rewrites nothing and says so",
          zero == 0 and json.dumps(same, sort_keys=True) == before)
    clash = M.collisions(plan, {"P2-abc": "P1"})
    check("ir12 a mapping onto an id the plan already holds is named before anything "
          "is written - a rename must never merge two records",
          clash == ["P1"], clash)

    # A REVIEW FINDING'S FIX TASK is an id too: `resolve-finding` writes it and
    # `reopen` finds the finding through it, so a move that left it behind would
    # point the finding at a task nobody can find.
    reviewed = {"phases": [
        {"id": "P2-abc", "tasks": [{"id": "P2-abc.1", "title": "u"}],
         "review": {"findings": [{"id": "P2-abc-R1", "fixTask": "P2-abc.1",
                                  "commit": "a" * 40}],
                    "preExistingNotCharged": [{"id": "X1", "fixTask": "P2-abc.1"}]}}]}
    moved, n = M.rename(reviewed, {"P2-abc.1": "P7.1"})
    review = moved["phases"][0]["review"]
    check("ir13 RED-FIRST: a finding's fixTask is renamed with the task it names, in "
          "BOTH lists a review holds findings in: %r" % (review,),
          review["findings"][0]["fixTask"] == "P7.1"
          and review["preExistingNotCharged"][0]["fixTask"] == "P7.1"
          and review["findings"][0]["id"] == "P2-abc-R1" and n == 3)
    import _manifest_phases as _phases
    check("ir14 the finding lists walked are the validator's own - one list in two "
          "layers, pinned rather than trusted: %r / %r"
          % (M.FINDING_LISTS, _phases.REVIEW_FINDING_LISTS),
          tuple(M.FINDING_LISTS) == tuple(_phases.REVIEW_FINDING_LISTS))
    import os
    import _output
    with open(os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json"),
              "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    shapes = [b.get("properties") or {} for b in schema["$defs"]["finding"]["oneOf"]
              if isinstance(b, dict) and b.get("type") == "object"]
    check("ir15 ...and the schema declares the fields a resolved finding carries, "
          "which is where this module's list of reference fields comes from: %r"
          % (sorted(shapes[0]) if shapes else None,),
          len(shapes) == 1 and "fixTask" in shapes[0] and "commit" in shapes[0])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__id_refs.py --selftest\n")
    raise SystemExit(2)
