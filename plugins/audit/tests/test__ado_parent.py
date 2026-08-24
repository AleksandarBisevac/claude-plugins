#!/usr/bin/env python3
"""
The cases for `_ado_parent.py` — where one audit item hangs, and whether it can.

Arithmetic over dicts, so there is no fixture directory below this file. The one
thing that is NOT hand-written is the backlog payload: `BACKLOG` is a trimmed
capture from a live project (test-audit-lab / audit-gate-scrum, 2026-08-24),
because a parser and every fixture it is tested against written by the same
person encode the same assumption, and this parser's whole job is to read
somebody else's document.

WHAT IS PINNED, and why each is here rather than trusted:

- **Precedence, with BOTH keys set.** `ap10` is the feature: an item's own
  declaration wins over `meta.ado.parentWorkItem`. The fixture uses two
  DIFFERENT ids, because a fixture where they agree cannot tell the two
  implementations apart.
- **Explicit null beats a set fallback.** `ap12` is the half that makes
  uncategorised a declared outcome; a resolver that treated null as absent
  would return the fallback and pass every other case here.
- **A manifest with no `adoParent` anywhere resolves as it did before.** `ap20`
  looks vacuous and is the ONLY case that fails if the new key ever becomes
  load-bearing on a file that does not carry it — the second-direction case
  `no-silent-pass` asks for.
- **The inert warning is emitted, and only where it applies.** `ap15` and its
  negative `ap16`: a task declaration under `phaseWorkItems` is warned about,
  and the same task under `phaseWorkItems: false` is honoured in silence.
- **The hierarchy family is split so no case can be satisfied by two rules.**
  `hp2` runs tier A with `levels=None`, so no rank could possibly explain it;
  `hp10`'s tier-B refusal names a parent that is NOT in the manifest, so no loop
  could; `hp12` asserts the refusal count is ZERO for equal ranks; `hp14` is the
  negative where a legitimate parent produces nothing at all.
- **Counts, never presence.** Every assertion below compares a NUMBER of
  refusals or a whole list, because a rule that fires twice and a rule that
  fires once both satisfy `in`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_parent as M                            # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402


# A trimmed capture of `az devops invoke --area work --resource
# backlogconfiguration --route-parameters project=audit-gate-scrum`, fields this
# module reads only. Scrum, so `bugsBehavior` is `asRequirements` — and note that
# `requirementBacklog.workItemTypes` does NOT name Bug, which is exactly why the
# behaviour field is the only thing that can place it.
BACKLOG = {
    "bugsBehavior": "asRequirements",
    "taskBacklog": {"id": "Microsoft.TaskCategory", "name": "Tasks", "rank": 1,
                    "workItemTypes": [{"name": "Task"}]},
    "requirementBacklog": {"id": "Microsoft.RequirementCategory",
                           "name": "Backlog items", "rank": 2,
                           "workItemTypes": [{"name": "Product Backlog Item"}]},
    "portfolioBacklogs": [
        {"id": "Microsoft.FeatureCategory", "name": "Features", "rank": 3,
         "workItemTypes": [{"name": "Feature"}]},
        {"id": "Microsoft.EpicCategory", "name": "Epics", "rank": 4,
         "workItemTypes": [{"name": "Epic"}]}],
}

# The same call against an Agile project on the same organization, trimmed to the
# one difference that matters: `asTasks`, so a Bug ranks with Task there. Two
# captures rather than one because a single project cannot show that the answer
# is per-project, which is the entire argument against a shipped table.
BACKLOG_AGILE = {
    "bugsBehavior": "asTasks",
    "taskBacklog": {"rank": 1, "workItemTypes": [{"name": "Task"}]},
    "requirementBacklog": {"rank": 2, "workItemTypes": [{"name": "User Story"}]},
    "portfolioBacklogs": [{"rank": 3, "workItemTypes": [{"name": "Feature"}]}],
}

LEVELS = {"Task": 1, "Product Backlog Item": 2, "Bug": 2, "Feature": 3,
          "Epic": 4}


def _phase(pid, parent="absent", link=None, tasks=None):
    """One phase. `parent` is 'absent' (no key at all), None (explicit null) or
    an id — the three states this module exists to tell apart, and a default of
    'absent' rather than None because those two are DIFFERENT documents."""
    out = {"id": pid, "title": pid, "status": "pending",
           "tasks": list(tasks or [])}
    if parent != "absent":
        out[M.FIELD] = None if parent is None else {"id": parent}
    if link is not None:
        out["ado"] = {"id": link}
    return out


def _task(tid, parent="absent", link=None):
    out = {"id": tid, "title": tid, "status": "pending"}
    if parent != "absent":
        out[M.FIELD] = None if parent is None else {"id": parent}
    if link is not None:
        out["ado"] = {"id": link}
    return out


def _sources(rows):
    return [r["source"] for r in rows]


def _parents(rows):
    return [r["parent"] for r in rows]


def _codes(result):
    """`(refusals, findings, warnings, unverified)` — every code, as LISTS, so a
    rule that fires twice reads differently from one that fires once.

    All four, never a subset: `refusals` is what the PUSH must not create and
    `findings`/`warnings` is how a MANIFEST is graded, and the whole
    compatibility decision lives in the gap between them. A case that read only
    `refusals` would be equally happy with a build that fails somebody's CI over
    a file they never edited.
    """
    return ([e["code"] for e in result["refusals"]],
            [e["code"] for e in result["findings"]],
            [e["code"] for e in result["warnings"]],
            [e["code"] for e in result["unverified"]])


def _cases(check):
    # --- the declaration's shape ----------------------------------------------
    check("ap1 an ABSENT adoParent is not a defect - it means 'use the "
          "fallback', which is an answer",
          M.declaration_findings({"id": "P1"}, "phase P1") == ([], []))
    check("ap2 an explicit null is not a defect either - it means 'nowhere', "
          "which is the other answer",
          M.declaration_findings({"id": "P1", M.FIELD: None}, "phase P1")
          == ([], []))
    _f, _w = M.declaration_findings({"id": "P1", M.FIELD: {"id": 42}}, "phase P1")
    check("ap3 a well-formed declaration is silent on both channels: %r %r"
          % (_f, _w), (_f, _w) == ([], []))
    for _bad, _why in ((7, "a bare integer - two spellings would be two answers"),
                       ("42", "a string"),
                       ([42], "a list")):
        _f, _w = M.declaration_findings({"id": "P1", M.FIELD: _bad}, "phase P1")
        check("ap4 %s is refused (%s): %r" % (repr(_bad), _why, _f),
              len(_f) == 1 and len(_w) == 0)
    _f, _w = M.declaration_findings({"id": "P1", M.FIELD: {}}, "phase P1")
    check("ap5 an object with no id is ONE finding naming the remedy (null), "
          "not a silent nothing: %r" % (_f,),
          len(_f) == 1 and "null" in _f[0])
    for _bad in (0, -3, True, "103205", 1.5, None):
        _f, _w = M.declaration_findings({"id": "P1", M.FIELD: {"id": _bad}},
                                        "phase P1")
        check("ap6 adoParent.id %r is not a work item id: %r" % (_bad, _f),
              len(_f) == 1)
    _f, _w = M.declaration_findings(
        {"id": "P1", M.FIELD: {"id": 1, "type": 3, "source": "guessed",
                               "observedAt": 7}}, "phase P1")
    check("ap7 every basis field is graded, and a bad `source` is a FINDING for "
          "adoLink.origin's reason - it reads as 'unrecorded' downstream, which "
          "is indistinguishable from the honest absence: %r" % (_f,),
          len(_f) == 3 and len(_w) == 0)
    _f, _w = M.declaration_findings(
        {"id": "P1", M.FIELD: {"id": 1, "Title": "x", "nonsense": 2}}, "phase P1")
    check("ap8 unknown keys inside a declaration are WARNINGS, never findings - "
          "a wrong CASE draws the did-you-mean and an unrecognisable one says "
          "so plainly, which is the split _manifest_vocab already draws: %r"
          % (_w,),
          _f == [] and len(_w) == 2 and "did you mean 'title'" in _w[0]
          and "did you mean" not in _w[1])

    # The DRY claim this module makes out loud. `_manifest_vocab._unknown_keys`
    # is a layer-mate and cannot be imported, so the loop is written twice - and
    # a comment saying two implementations agree is what this repo's token
    # formatter already proved worthless. This compares them instead.
    _probe = {"id": 1, "Title": "x", "nonsense": 2, "_internal": 3}
    _mine = M.unknown_declaration_keys(_probe, "phase P1")
    _theirs = []
    _vocab._unknown_keys(_probe, set(M.KNOWN_PARENT), "phase P1.adoParent",
                         _theirs)
    check("ap9 ...and the second copy of that loop answers exactly what "
          "_manifest_vocab._unknown_keys answers, pinned rather than claimed: "
          "%r vs %r" % (_mine, _theirs),
          _mine == _theirs)

    # --- resolution: the five rules -------------------------------------------
    _ado = {"parentWorkItem": 500, "phaseWorkItems": False}
    _res = M.resolve(_phase("P1", parent=900), ado=_ado)
    check("ap10 a declared adoParent BEATS meta.ado.parentWorkItem with both "
          "set - and the two ids differ, or the case could not tell the "
          "implementations apart: %r" % (_res["id"],),
          _res["id"] == 900 and _res["source"] == "item")
    check("ap11 ...and the basis names the declaration rather than the "
          "fallback: %r" % (_res["basis"],),
          "adoParent" in _res["basis"] and "parentWorkItem" not in _res["basis"])
    _res = M.resolve(_phase("P1", parent=None), ado=_ado)
    check("ap12 an EXPLICIT null beats a set fallback: the phase hangs under "
          "nothing, and the source is still the ITEM because the item is what "
          "said so: %r" % (_res,),
          _res["id"] is None and _res["source"] == "item")
    check("ap13 ...and its basis says the fallback was deliberately not used, "
          "because 'no parent' and 'nobody looked' must not read alike: %r"
          % (_res["basis"],),
          "500" in _res["basis"])
    _res = M.resolve(_phase("P1"), ado=_ado)
    check("ap14 absent falls through to meta.ado.parentWorkItem, source `meta`",
          _res["id"] == 500 and _res["source"] == "meta")
    _res = M.resolve(_task("P1.1", parent=900),
                     ado={"parentWorkItem": 500},
                     phase=_phase("P1", link=700))
    check("ap15 a task's adoParent is INERT while phaseWorkItems is on: it "
          "hangs under its phase's work item, and the ignored declaration draws "
          "exactly one warning rather than being dropped: %r" % (_res,),
          _res["id"] == 700 and _res["source"] == "phase"
          and len(_res["warnings"]) == 1 and "INERT" in _res["warnings"][0])
    # The second direction. A warning that became unconditional would fire here
    # too, and every case above would still pass.
    _res = M.resolve(_task("P1.1", parent=900),
                     ado={"parentWorkItem": 500, "phaseWorkItems": False},
                     phase=_phase("P1", link=700))
    check("ap16 ...and with phaseWorkItems FALSE the same declaration is "
          "honoured, in silence: %r" % (_res,),
          _res["id"] == 900 and _res["source"] == "item"
          and _res["warnings"] == [])
    _res = M.resolve(_task("P1.1"), ado={}, phase=_phase("P1", link=700))
    check("ap22 a task that declares NOTHING under phaseWorkItems draws no "
          "warning at all - the case that fails if the inert warning ever "
          "becomes unconditional, which ap16 cannot see because it turns "
          "phaseWorkItems off and never reaches the branch: %r" % (_res,),
          _res["warnings"] == [] and _res["id"] == 700)
    _res = M.resolve(_task("P1.1"), ado={}, phase=_phase("P1"))
    check("ap17 a task whose phase is not linked yet resolves to no id, source "
          "`phase`, and a basis saying the push creates the phase item first - "
          "not to the fallback and not to an error: %r" % (_res,),
          _res["id"] is None and _res["source"] == "phase"
          and "creates the phase item first" in _res["basis"])
    _res = M.resolve(_phase("P1"), ado={})
    check("ap18 neither the item nor meta names a parent: source `none`, and a "
          "basis rather than a blank - an uncategorised create is an ANSWER: %r"
          % (_res,),
          _res["id"] is None and _res["source"] == "none" and _res["basis"])
    check("ap19 every source this module hands out is in its own vocabulary, so "
          "a surface switching on it cannot meet a fifth value",
          set(_sources(M.inventory(
              [_phase("P1", parent=900, tasks=[_task("P1.1")]),
               _phase("P2", parent=None), _phase("P3")],
              {"parentWorkItem": 500})["rows"])) <= set(M.PARENT_SOURCE))

    # THE VACUOUS-LOOKING ONE, and the only case that fails if `adoParent` ever
    # becomes load-bearing on a manifest that does not carry it.
    _plain = [_phase("P1", tasks=[_task("P1.1"), _task("P1.2")]),
              _phase("P2", tasks=[_task("P2.1")])]
    _rows = M.inventory(_plain, {"parentWorkItem": 500,
                                 "phaseWorkItems": False})["rows"]
    check("ap20 a manifest with NO adoParent anywhere resolves exactly as it "
          "did before this feature: every phase AND every task under "
          "meta.ado.parentWorkItem, every source `meta`, no warnings: %r"
          % (_parents(_rows),),
          _parents(_rows) == [500] * 5 and _sources(_rows) == ["meta"] * 5)
    _rows = M.inventory(_plain, {"phaseWorkItems": False})["rows"]
    check("ap21 ...and with no fallback either, the same manifest is five "
          "uncategorised creates rather than an error: %r" % (_sources(_rows),),
          _parents(_rows) == [None] * 5 and _sources(_rows) == ["none"] * 5)

    # --- the project's own backlog ranks --------------------------------------
    _levels = M.levels_from_backlog_config(BACKLOG)
    check("bl1 the captured Scrum payload ranks the whole ladder, Bug included: "
          "%r" % (_levels["levels"],),
          _levels["levels"] == LEVELS)
    check("bl2 ...and Bug is placed by bugsBehavior alone - the payload's "
          "requirementBacklog.workItemTypes does not name it",
          "Bug" not in [t["name"] for t in
                        BACKLOG["requirementBacklog"]["workItemTypes"]])
    _agile = M.levels_from_backlog_config(BACKLOG_AGILE)
    check("bl3 the Agile project on the SAME organization ranks Bug with Task, "
          "which is why no table ships here: %r" % (_agile["levels"],),
          _agile["levels"] == {"Task": 1, "Bug": 1, "User Story": 2,
                               "Feature": 3})
    check("bl4 the basis carries the command that re-derives it, so a cached "
          "block can be checked rather than believed: %r" % (_levels["basis"],),
          "backlogconfiguration" in _levels["basis"])
    for _junk in (None, {}, [], "levels", {"bugsBehavior": "asTasks"},
                  {"taskBacklog": {"rank": "1"}}):
        check("bl5 %r is not a backlog configuration, and the answer is None "
              "rather than an empty ladder - an unreadable response must not "
              "read as 'this project ranks nothing'" % (_junk,),
              M.levels_from_backlog_config(_junk) is None)

    # --- tier A: structural, offline, and it needs no ranks -------------------
    # LEVELS IS DELIBERATELY None IN THIS FAMILY. Tier A must stand on the
    # manifest's own ids alone, so a case that also had ranks available could be
    # satisfied by tier B and prove nothing about tier A.
    _self = [_phase("P1", parent=700, link=700)]
    _res = M.hierarchy_violations(M.inventory(_self, {})["rows"], None)
    check("hp1 A1: a phase declaring its OWN work item is refused exactly once, "
          "with no ranks anywhere: %r" % (_codes(_res),),
          _codes(_res) == (["A1"], ["A1"], [], []))
    # The live bug, in the shape it was measured in: a phase whose declared
    # parent is the very task this manifest hangs under it.
    _loop = [_phase("P1", parent=31, link=30, tasks=[_task("P1.1", link=31)])]
    _res = M.hierarchy_violations(M.inventory(_loop, {})["rows"], None)
    check("hp2 A2: a phase hung under its own child is refused, offline and "
          "with levels=None - this is the pair that exists on a real board "
          "right now, because ADO accepted it. BOTH members of the loop are "
          "refused, because either link alone is fine and it is the pair that "
          "closes it - naming a culprit would mean guessing which edge was "
          "meant: %r" % (_codes(_res),),
          _codes(_res) == (["A2", "A2"], ["A2", "A2"], [], []))
    _first = (_res["refusals"] or [{}])[0]
    check("hp3 ...and the refusal names the loop and the item, so the operator "
          "has somewhere to go: %r" % (_first.get("message"),),
          _first.get("id") == "P1" and "#31" in _first.get("message", ""))
    _pair = [_phase("P1", parent=500, link=501),
             _phase("P2", parent=501, link=500)]
    _res = M.hierarchy_violations(M.inventory(_pair, {})["rows"], None)
    check("hp4 A3: two phases declaring each other are refused ONCE EACH - both "
          "items are unbuildable, and one refusal would leave the other looking "
          "creatable: %r" % (_codes(_res),),
          _codes(_res) == (["A3", "A3"], ["A3", "A3"], [], []))
    _unlinked = [_phase("P1", parent=31, tasks=[_task("P1.1", link=31)])]
    _res = M.hierarchy_violations(M.inventory(_unlinked, {})["rows"], None)
    check("hp5 a phase that is not linked yet draws NO structural refusal - "
          "there is no id to close a loop through, and inventing one would be "
          "the confident wrong answer: %r" % (_codes(_res),),
          _codes(_res) == ([], [], [], ["B0"]))

    # --- the source split, which is where the compatibility promise lives -----
    # TWO FIXTURES DESCRIBING THE SAME BROKEN BOARD, differing only in WHICH KEY
    # put the parent there. Neither can be satisfied by a rule that always warns
    # or always refuses, because they demand opposite verdicts from the same
    # function on the same shape - and both demand the SAME push refusal.
    _inherited = M.inventory(
        [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 30},
          "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                     "ado": {"id": 31}}]}],
        {"parentWorkItem": 31})["rows"]
    _res = M.hierarchy_violations(_inherited, None)
    check("hp20 a loop reachable with NO adoParent anywhere - the old single "
          "meta.ado.parentWorkItem pointing at one of the audit's own tasks - "
          "is refused by the PUSH and only WARNED about by the manifest. "
          "COMPATIBILITY.md promises a file that validates keeps validating, "
          "and that file could be written before this feature existed: %r"
          % (_codes(_res),),
          _codes(_res) == (["A2", "A2"], [], ["A2", "A2"], []))
    check("hp21 ...and the TASK in that loop is warned about too, not just the "
          "phase. Its own source is `phase`, so a per-row source test would "
          "call it a finding and fail a file nobody edited - the loop is what "
          "decides, not the row: %r"
          % ([(e["id"], e["severity"]) for e in _res["refusals"]],),
          [e["severity"] for e in _res["refusals"]] == ["warning", "warning"])
    _declared = M.inventory(
        [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 30},
          "adoParent": {"id": 31},
          "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                     "ado": {"id": 31}}]}], {})["rows"]
    _res = M.hierarchy_violations(_declared, None)
    check("hp22 ...and the SAME loop written as an adoParent is a FINDING: no "
          "manifest predating the key can carry one, so refusing it is fully "
          "additive and the promise is intact without an exception: %r"
          % (_codes(_res),),
          _codes(_res) == (["A2", "A2"], ["A2", "A2"], [], []))
    check("hp23 ...and BOTH spellings are refused by the push identically - the "
          "two surfaces disagree on the manifest verdict and agree completely "
          "on whether the link may be created, which is the whole point of "
          "grading them in one function",
          [e["code"] for e in M.hierarchy_violations(_inherited, None)["refusals"]]
          == [e["code"] for e in _res["refusals"]])
    check("hp24 findings and warnings PARTITION the graded entries, so a caller "
          "reads one key and never subtracts one bucket from another",
          all(len(r["findings"]) + len(r["warnings"])
              == len([e for e in r["refusals"]])
              + len([e for e in r["warnings"] if e["code"] == "B2"])
              for r in (M.hierarchy_violations(_inherited, None),
                        M.hierarchy_violations(_declared, None))))

    # --- tier B: the ranks, and only where a rank exists ----------------------
    # THE PARENT IS NOT IN THIS MANIFEST, so no loop can be drawn through it and
    # tier A cannot possibly be what reddens this case.
    _inverted = [_phase("P1", link=800,
                        tasks=[])]
    _inverted[0][M.FIELD] = {"id": 41, "type": "Task"}
    _rows = M.inventory(_inverted, {"types": {"pbi": "Product Backlog Item"}})["rows"]
    _res = M.hierarchy_violations(_rows, LEVELS)
    check("hp10 B1: a Product Backlog Item hung under a Task is refused once, "
          "and 41 is NOT an id this manifest carries - so tier A has nothing to "
          "walk and only the ranks can explain this: %r" % (_codes(_res),),
          _codes(_res) == (["B1"], [], ["B1"], []))
    check("hp11 ...and the same pair with levels=None is NOT verified rather "
          "than refused: a missing basis is not evidence of a defect: %r"
          % (_codes(M.hierarchy_violations(_rows, None)),),
          _codes(M.hierarchy_violations(_rows, None)) == ([], [], [], ["B0"]))
    _equal = [_phase("P1", link=800)]
    _equal[0][M.FIELD] = {"id": 41, "type": "Product Backlog Item"}
    _res = M.hierarchy_violations(
        M.inventory(_equal, {"types": {"pbi": "Product Backlog Item"}})["rows"],
        LEVELS)
    check("hp12 B2: EQUAL rank is a note and the refusal count is ZERO - a Bug "
          "under a PBI is rank 2 under rank 2 wherever bugsBehavior is "
          "asRequirements, and a checker that refuses a deliberate arrangement "
          "gets switched off: %r" % (_codes(_res),),
          len(_res["refusals"]) == 0 and _codes(_res) == ([], [], ["B2"], []))
    _unranked = [_phase("P1", link=800)]
    _unranked[0][M.FIELD] = {"id": 41, "type": "Deliverable"}
    _res = M.hierarchy_violations(
        M.inventory(_unranked, {"types": {"pbi": "Product Backlog Item"}})["rows"],
        LEVELS)
    check("hp13 a type this project does not rank is NOT VERIFIED and named, "
          "never assumed into a refusal: %r" % (_codes(_res),),
          _codes(_res) == ([], [], [], ["B0"])
          and "Deliverable" in (_res["unverified"] or [{}])[0].get("message", ""))
    # THE NEGATIVE. A check that became unconditional would fire here, and every
    # case above would still pass.
    _good = [_phase("P1", link=800, tasks=[_task("P1.1", link=801)])]
    _good[0][M.FIELD] = {"id": 41, "type": "Feature"}
    _res = M.hierarchy_violations(
        M.inventory(_good, {"types": {"pbi": "Product Backlog Item",
                                      "task": "Task"}})["rows"], LEVELS)
    check("hp14 a legitimate ladder - Task under PBI under Feature - produces "
          "no refusal, no note and nothing unverified: %r" % (_codes(_res),),
          _codes(_res) == ([], [], [], []) and _res["checked"] == 2)
    check("hp15 an uncategorised item is not a hierarchy question at all, so it "
          "is neither checked nor refused: %r"
          % (M.hierarchy_violations(M.inventory([_phase("P1")], {})["rows"],
                                    LEVELS),),
          M.hierarchy_violations(M.inventory([_phase("P1")], {})["rows"],
                                 LEVELS)["checked"] == 0)
    check("hp16 an empty plan reports zero CHECKED rather than a clean bill - "
          "'nothing was wrong' and 'nothing was looked at' must not print the "
          "same way",
          M.hierarchy_violations([], LEVELS)
          == {"refusals": [], "findings": [], "warnings": [], "unverified": [],
              "checked": 0})

    # --- the sentences the confirm gate prints --------------------------------
    _clean = M.inventory([_phase("P1", parent=41, link=800)],
                         {"types": {"pbi": "Feature"}})["rows"]
    _lines = M.plan_lines(_clean, M.hierarchy_violations(_clean, LEVELS))
    check("pl1 the plan's head prints BOTH counts at zero - a number that "
          "appears only on bad news cannot be told apart from a number nobody "
          "computed: %r" % (_lines[0],),
          "0 refused" in _lines[0] and "0 uncategorised" in _lines[0])
    _mixed = M.inventory([_phase("P1", parent=31, link=30,
                                 tasks=[_task("P1.1", link=31)]),
                          _phase("P2")], {})["rows"]
    _res = M.hierarchy_violations(_mixed, None)
    _lines = M.plan_lines(_mixed, _res)
    check("pl2 ...and every refusal is printed against the item it refuses, so "
          "the operator sees it before deciding rather than after the item is "
          "on the board - counted against the refusals rather than asserted "
          "present: %r" % (_lines,),
          len([x for x in _lines if x.strip().startswith("REFUSED")])
          == len(_res["refusals"]) == 2)
    check("pl3 ...and every item still gets a line of its own, refused or not, "
          "so the block is the whole plan and not a defect list: %r" % (_lines,),
          len([x for x in _lines if " -> " in x]) == 3)
    _open = M.inventory([_phase("P1", parent=41, link=800),
                         _phase("P2", parent=42, link=801)], {})["rows"]
    _lines = M.plan_lines(_open, M.hierarchy_violations(_open, None))
    check("pl4 ...and an unfetched hierarchy prints one NOT VERIFIED line per "
          "link rather than a silence, which is what the operator needs to "
          "decide whether to run /audit:sync parents first: %r" % (_lines,),
          len([x for x in _lines if "NOT VERIFIED" in x]) == 2
          and "2 not verified" in _lines[-3])

    # --- the marker a WRITER needs, because JSON has no third value ------------
    # Absent, null and an object are three stored states; a patch key is either
    # present or not, so a panel that could only send `null` or an object could
    # reach two of the three and would have to spell the third by pruning - which
    # is exactly the answer null already means here. These cases hold the marker
    # apart from a real declaration in both directions.
    check("uf1 use_fallback() hands back a FRESH object each call, so a caller "
          "that edits one cannot reach the next - the shape is named once here "
          "and owned by nobody",
          M.use_fallback() == M.use_fallback()
          and M.use_fallback() is not M.use_fallback())
    _uf = M.use_fallback()
    _uf["id"] = 41
    check("uf2 ...and the edit above did not travel: the next call is clean",
          "id" not in M.use_fallback(), repr(M.use_fallback()))
    _uf_f, _uf_w = M.declaration_findings({"id": "P1", M.FIELD: M.use_fallback()},
                                          "phase P1")
    check("uf3 the marker is REFUSED as a declaration, so a writer that forgets "
          "to translate it gets a refusal and never a parent named after it: %r"
          % (_uf_f,),
          len(_uf_f) == 1 and "requires an 'id'" in _uf_f[0])
    check("uf4 is_use_fallback is strict about BOTH halves - a truthy 1 is not "
          "True, and a marker carrying anything else is a declaration somebody "
          "wrote, not an instruction",
          M.is_use_fallback(M.use_fallback())
          and not M.is_use_fallback({"useFallback": 1})
          and not M.is_use_fallback({"useFallback": True, "id": 41})
          and not M.is_use_fallback(None)
          and not M.is_use_fallback({"id": 41}))
    check("uf5 ...and resolve() never SEES one: the marker is a patch spelling, "
          "so an item still carrying it resolves as the unusable declaration it "
          "is rather than silently as the fallback it was meant to become",
          M.resolve({"id": "P1", M.FIELD: M.use_fallback()},
                    {"parentWorkItem": 41})["id"] is None)



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_parent.py --selftest\n")
    raise SystemExit(2)
