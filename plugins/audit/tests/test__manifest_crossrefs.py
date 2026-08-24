#!/usr/bin/env python3
"""
The cases for `_manifest_crossrefs.py` — how one part of the manifest refers to
another.

Every function here takes the INDEX `_manifest_phases._walk_phases` returns and
answers one question about a reference. That is why the cases below build the
index by hand rather than round-tripping a document: a check that can be called
with five keys and no manifest anywhere near it is a check whose contract is
visible, and the hand-built index is what proves the contract is real rather
than a description of how `validate()` happens to call it.

The questions, and the reason each is a finding rather than a warning: an
ambiguous id makes every reference to it resolve to whichever the lookup reached
first; an unresolved `blockedBy` can never be satisfied, and neither can one
inside a cycle; a fileIndex that disagrees with a task's `files` sends the next
executor to the wrong file; a one-sided bug link is two records that each look
fine and disagree about which fix belongs to which report.

Proposals are the one place the same array carries two classes of entry.
Payload-bearing proposals have their vocabulary ENFORCED; legacy free-form ones
are tolerated, so no pre-0.33 manifest goes red — and both directions have a
case, because a rule that fires on everything is as wrong as one that never
fires.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_crossrefs as M                    # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _manifest_rules as _rules                   # noqa: E402


def _index(**kw):
    """An index with every key `_walk_phases` produces, empty by default."""
    idx = {"phase_ids": [], "task_ids": [], "task_by_id": {}, "task_files": {},
           "bug_links": [], "bug_list": [], "bug_ids": [], "bug_by_id": {}}
    idx.update(kw)
    return idx


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the bugs half of the index ---
    idx = M._index_bugs({"bugs": [{"id": "BUG-1", "taskId": "P0.1"},
                                  "junk", {"no": "id"}]})
    check("mc1 `_index_bugs` indexes only the entries that ARE objects with "
          "an id, and reports nothing - an index is not a check",
          idx["bug_ids"] == ["BUG-1"] and list(idx["bug_by_id"]) == ["BUG-1"]
          and len(idx["bug_list"]) == 3, idx)
    idx = M._index_bugs({"bugs": "nope"})
    check("mc2 ...and a non-list `bugs` yields an empty index rather than "
          "raising: the wrong-type diagnostic is _check_bugs' to give",
          idx["bug_list"] == [] and idx["bug_ids"] == [], idx)

    check("mc3 `_live_ids` keeps DUPLICATES and document order - phases, then "
          "tasks, then bugs - because _check_unique_ids is the thing that "
          "finds them and this must not dedupe them away",
          M._live_ids(_index(phase_ids=["P0", "P0"], task_ids=["P0.1"],
                             bug_ids=["BUG-1"]))
          == ["P0", "P0", "P0.1", "BUG-1"])

    f, w = M._check_unique_ids(_index(phase_ids=["P0"], task_ids=["P0"]))
    check("mc4 a phase and a task wearing one id is a finding: blockedBy "
          "resolves against both namespaces together, so every reference to "
          "it would be ambiguous",
          len(f) == 1 and "duplicate id: P0" in f[0] and w == [], (f, w))
    f, w = M._check_unique_ids(_index(phase_ids=["P0"], task_ids=["P0.1"]))
    check("mc5 ...and distinct ids are silent, which is the case that fails "
          "if the `seen` set is populated before the test rather than after",
          f == [] and w == [], (f, w))

    # --- references and cycles ---
    f = M._ref_findings("P0.1", "task X", "blockedBy", {"P0.1"}, "a task")
    check("mc6 a non-array reference list is reported as a wrong type rather "
          "than iterated per-character",
          len(f) == 1 and "must be an array" in f[0], f)
    f = M._ref_findings([7], "task X", "blockedBy", {"P0.1"}, "a task")
    check("mc7 ...and a non-string entry is reported rather than crashing the "
          "set-membership test", len(f) == 1 and "must be a string id" in f[0],
          f)
    f = M._ref_findings(["P9"], "task X", "blockedBy", {"P0.1"}, "a task")
    check("mc8 ...and an id that resolves to nothing is named with what it "
          "was looked for in", len(f) == 1 and "does not resolve" in f[0], f)
    f = M._ref_findings(["P0.1"], "task X", "blockedBy", {"P0.1"}, "a task")
    check("mc9 ...and one that resolves is silent", f == [], f)

    phases = [{"id": "P0", "status": "pending", "tasks": [
        {"id": "P0.1", "status": "pending", "dependsOn": ["P0.2"]},
        {"id": "P0.2", "status": "pending", "dependsOn": ["P0.1"]}]}]
    f, w = M._check_refs_and_cycles(
        phases, _index(phase_ids=["P0"], task_ids=["P0.1", "P0.2"]))
    check("mc10 two tasks waiting on each other is a dependency cycle, "
          "reported once with the path spelled out",
          len([x for x in f if "dependency cycle" in x]) == 1, f)
    phases = [{"id": "P0", "status": "pending", "tasks": [
        {"id": "P0.1", "status": "pending", "blockedBy": ["P0"]}]}]
    f, w = M._check_refs_and_cycles(
        phases, _index(phase_ids=["P0"], task_ids=["P0.1"]))
    check("mc11 ...and a task blocked by its OWN phase is a cycle too, "
          "because a phase is done only after its tasks - the deadlock the "
          "phase->task edge exists to catch",
          any("dependency cycle" in x for x in f), f)
    phases = [{"id": "P0", "status": "pending", "tasks": [
        {"id": "P0.1", "status": "pending", "dependsOn": []},
        {"id": "P0.2", "status": "pending", "dependsOn": ["P0.1"]}]}]
    f, w = M._check_refs_and_cycles(
        phases, _index(phase_ids=["P0"], task_ids=["P0.1", "P0.2"]))
    check("mc12 ...and an acyclic plan is silent, which is the case that "
          "fails if the cycle walk starts reporting every visited edge",
          f == [] and w == [], (f, w))

    # --- fileIndex, both directions ---
    f, w = M._check_file_index({"fileIndex": {"src/a.ts": ["P0.9"]}},
                               _index(task_ids=["P0.1"]))
    check("mc13 forward: a fileIndex entry naming a task that does not exist "
          "is a finding", len(f) == 1 and "does not exist" in f[0], f)
    f, w = M._check_file_index({"fileIndex": {}},
                               _index(task_ids=["P0.1"],
                                      task_files={"P0.1": ["src/a.ts"]}))
    check("mc14 backward: a file a task claims but the index does not list is "
          "a finding - the direction a schema cannot express, and the one "
          "that catches the common drift",
          len(f) == 1 and "missing from fileIndex" in f[0], f)
    f, w = M._check_file_index(
        {"fileIndex": {"src/a.ts:12-40": ["P0.1"]}},
        _index(task_ids=["P0.1"], task_files={"P0.1": ["src/a.ts:99"]}))
    check("mc15 ...and both sides are compared with their line ranges "
          "stripped, so `a.ts:12-40` and `a.ts:99` are the same file",
          f == [], f)
    f, w = M._check_file_index({}, _index(task_ids=["P0.1"]))
    check("mc16 an absent fileIndex is silent: the key is optional",
          f == [] and w == [], (f, w))

    # --- bugs, and the reciprocal link ---
    task = {"id": "P0.1", "bugId": "BUG-2"}
    bug = {"id": "BUG-1", "title": "b", "status": "open", "taskId": "P0.1"}
    idx = _index(task_ids=["P0.1"], task_by_id={"P0.1": task},
                 bug_list=[bug], bug_ids=["BUG-1"], bug_by_id={"BUG-1": bug})
    f, w = M._check_bugs({"bugs": [bug]}, idx)
    check("mc17 a bug pointing at a task whose bugId names a DIFFERENT bug is "
          "a finding: two records that each look fine and disagree about "
          "which fix belongs to which report",
          any("link must be reciprocal" in x for x in f), f)
    bug2 = {"id": "BUG-1", "title": "b", "status": "open", "taskId": "P0.1"}
    task2 = {"id": "P0.1", "bugId": "BUG-1"}
    idx = _index(task_ids=["P0.1"], task_by_id={"P0.1": task2},
                 bug_list=[bug2], bug_ids=["BUG-1"], bug_by_id={"BUG-1": bug2},
                 bug_links=[("task P0.1", "P0.1", "BUG-1")])
    f, w = M._check_bugs({"bugs": [bug2]}, idx)
    check("mc18 ...and a link that IS reciprocal from both ends is silent - "
          "the case that fails if the comparison is inverted",
          f == [] and w == [], (f, w))
    bad = {"id": "BUG-x", "title": "b", "status": "open"}
    f, w = M._check_bugs({"bugs": [bad]},
                         _index(bug_list=[bad], bug_ids=["BUG-x"],
                                bug_by_id={"BUG-x": bad}))
    check("mc19 a bug id that is not BUG-<number> is a finding: the id is "
          "allocated by /audit:bug and read back by pattern",
          any("must match BUG-<number>" in x for x in f), f)

    # --- proposals ---
    prop = {"id": "PROP-1", "status": "proposed",
            "payload": {"phase": {"id": "P0", "title": "T", "tasks": []}}}
    f, w = M._check_proposals({"proposals": [prop]},
                              _index(phase_ids=["P0"], task_ids=[]))
    check("mc20 a parked payload reserving an id the LIVE plan already spends "
          "is a finding: materialize re-allocates, but a parked payload "
          "should never share an id with the live plan",
          any("collides with a live id" in x for x in f), f)
    f, w = M._check_proposals({"proposals": [{"note": "someday"}]}, _index())
    check("mc21 ...while a legacy free-form entry with no payload is "
          "tolerated - unknown-key warnings at most, so no pre-0.33 manifest "
          "goes red", f == [], (f, w))
    prop = {"id": "PROP-1", "status": "proposed",
            "payload": {"phase": {"id": "PX", "title": "T", "tasks": [],
                                  "blockedBy": ["P9"]}}}
    f, w = M._check_proposals({"proposals": [prop]}, _index())
    check("mc22 ...and a staged reference naming nothing anywhere is only a "
          "WARNING: the payload is staged, not live, and materialize "
          "re-checks refs anyway",
          f == [] and any("materialize will ask about it" in x for x in w),
          (f, w))
    prop = {"id": "PROP-1", "status": "proposed", "materializedAs": "P0",
            "payload": {"phase": {"id": "PX", "title": "T", "tasks": []}}}
    f, w = M._check_proposals({"proposals": [prop]}, _index(phase_ids=["P0"]))
    check("mc23 ...and `materializedAs` set while status is still 'proposed' "
          "is a finding: /audit:propose writes both together",
          any("must be 'materialized'" in x for x in f), f)

    # The DROP pair. `propose.md` has always ASKED for the justification, but
    # prose cannot enforce it and the panel can drop too now — an archive whose
    # entries do not say why is a tombstone, and that command's own words are that
    # a later reader must find why the work was declined.
    _pay = {"phase": {"id": "PX", "title": "T", "tasks": []}}
    prop = {"id": "PROP-1", "status": "dropped", "payload": _pay}
    f, w = M._check_proposals({"proposals": [prop]}, _index())
    check("mc27 a dropped proposal with no `notes` is a finding — dropping is "
          "archiving, and an archive that does not say why cannot be read later",
          any("no `notes` justification" in x for x in f), f)
    prop = {"id": "PROP-1", "status": "dropped", "notes": "duplicate of PROP-4",
            "payload": _pay}
    f, w = M._check_proposals({"proposals": [prop]}, _index())
    check("mc28 ...and with one it is clean, so the rule is about the REASON and "
          "not about dropping", f == [], (f, w))
    prop = {"id": "PROP-1", "status": "proposed", "droppedAt": "2026-08-21T10:00:00Z",
            "payload": _pay}
    f, w = M._check_proposals({"proposals": [prop]}, _index())
    check("mc29 `droppedAt` set while status is not 'dropped' is a finding, the "
          "same way `materializedAs` is — the pair is written together",
          any("droppedAt is set but status" in x for x in f), f)

    # --- the aliases ---
    _names = ("_cycle_findings", "_index_bugs", "_live_ids",
              "_check_unique_ids", "_ref_findings", "_check_refs_and_cycles",
              "_check_file_index", "_check_bugs", "_check_proposals")
    _forked = [n for n in _names if getattr(_rules, n) is not getattr(M, n)]
    check("mc24 every name `_manifest_rules` re-exports from here IS this "
          "module's function: %r" % (_forked,), _forked == [])
    _shared = ("_unknown_keys", "_safe_list", "_require_fields", "_check_ado",
               "_strip_line_suffix", "BUG_ID_RE", "BUG_STATUS", "KNOWN_BUG",
               "KNOWN_PROPOSAL", "PROPOSAL_STATUS", "PROP_ID_RE")
    _drift = [n for n in _shared if getattr(M, n) is not getattr(_vocab, n)]
    check("mc25 ...and every word and shape check it reads is "
          "`_manifest_vocab`'s object: %r" % (_drift,), _drift == [])

    # --- phase priority: a claim with nothing behind it ------------------------
    # EVERY ONE OF THESE IS A WARNING, AND THAT IS THE DECISION RATHER THAN AN
    # OVERSIGHT. A finding would make the manifest INVALID, which refuses the next
    # `/audit:task add`, reds `--gate` on the `invalid` condition, and would make
    # `set-priority.py --force` roll back the very write it was asked to force. A
    # disagreement about ORDER must not stop the pipeline; it must not be silent
    # either, which is what these say.
    def _pplan(phases):
        return {"meta": {"version": 2}, "phases": phases}

    def _pw(phases):
        f, w = M._check_priority(_pplan(phases), phases)
        return (f, w)

    _clean = [{"id": "P1", "title": "a", "status": "pending", "tasks": []},
              {"id": "P2", "title": "b", "status": "pending",
               "priority": 1, "tasks": []},
              {"id": "P3", "title": "c", "status": "pending",
               "priority": 3, "tasks": []}]
    check("pc0 SECOND-DIRECTION CASE: a clean plan - one holder of tier 1, a "
          "shared tier, an unpinned phase - produces NOT ONE priority line. "
          "This is the case that goes red if any of the four rules below "
          "becomes unconditional, and every one of them would then fire on "
          "nearly every manifest",
          _pw(_clean) == ([], []), repr(_pw(_clean)))
    _two = [{"id": "P1", "title": "a", "status": "pending",
             "priority": 1, "tasks": []},
            {"id": "P2", "title": "b", "status": "pending",
             "priority": 1, "tasks": []}]
    _f, _w = _pw(_two)
    check("pc1 two holders of tier 1: a WARNING, not a finding - the pipeline "
          "keeps running, which is the only way the tie-break below can ever be "
          "used",
          _f == [] and len(_w) == 1, repr((_f, _w)))
    check("pc2 ...and the warning NAMES the tie-break and its winner, because a "
          "silent tie-break is an order nobody can explain",
          "P1 wins because it comes first in the manifest" in _w[0], repr(_w))
    _blocked = [{"id": "P2", "title": "b", "status": "pending", "tasks": []},
                {"id": "P5", "title": "e", "status": "pending", "priority": 1,
                 "blockedBy": ["P2"], "tasks": []}]
    _f, _w = _pw(_blocked)
    check("pc3 a pinned phase waiting on unfinished work is reported: a "
          "priority whose own dependencies contradict it is a claim with no "
          "basis",
          _f == [] and len(_w) == 1 and "waits on P2" in _w[0], repr((_f, _w)))
    _done = [{"id": "P2", "title": "b", "status": "done", "tasks": []},
             {"id": "P5", "title": "e", "status": "pending", "priority": 1,
              "blockedBy": ["P2"], "tasks": []}]
    check("pc4 SECOND-DIRECTION CASE: the SAME pin with its blocker DONE draws "
          "nothing. The fixture differs from pc3 in one status, so a version "
          "that reported every prioritised phase with a blockedBy would fail "
          "here and pass there",
          _pw(_done) == ([], []), repr(_pw(_done)))
    _finished = [{"id": "P2", "title": "b", "status": "pending", "tasks": []},
                 {"id": "P5", "title": "e", "status": "cancelled",
                  "priority": 1, "blockedBy": ["P2"], "tasks": []}]
    check("pc5 ...and a phase that is itself finished is not reported either - "
          "a cancelled or done phase will not run again, so its pin is history "
          "rather than a wait",
          _pw(_finished) == ([], []), repr(_pw(_finished)))
    _junk = [{"id": "P1", "title": "a", "status": "pending",
              "priority": "1", "tasks": []},
             {"id": "P2", "title": "b", "status": "pending",
              "priority": 0, "tasks": []}]
    _f, _w = _pw(_junk)
    check("pc6 a priority that is not a positive integer is named, once per "
          "phase, with the value - it orders nothing, and a value with no "
          "effect that nobody mentions is the silent drop this refuses",
          _f == [] and len(_w) == 2 and "'1'" in _w[0] and "0" in _w[1],
          repr((_f, _w)))
    check("pc7 ...and the whole check runs through `validate()` too, so these "
          "reach every consumer of the rules rather than only a direct caller",
          any("both hold priority 1" in line
              for line in _rules.validate(_pplan(_two))[1]),
          repr(_rules.validate(_pplan(_two))[1]))
    check("pc8 ...and `validate()` still reports NO findings for them, which is "
          "what keeps a scheduling wish from locking the pipeline",
          _rules.validate(_pplan(_two))[0] == [],
          repr(_rules.validate(_pplan(_two))[0]))

    # --- where the work hangs on the board ------------------------------------
    # The SEVERITY SPLIT is the whole decision here, so both halves are counted
    # rather than asserted present: tier A is offline, always has a basis and
    # makes the manifest INVALID; tier B reads a cache with a `fetchedAt` and
    # can only ever warn, because refusing a manifest on month-old evidence
    # would red somebody's CI over a stale file.
    def _plan(ado, phases):
        return {"meta": {"version": 2, "ado": ado}, "phases": phases}

    _loop = _plan({"phaseWorkItems": False},
                  [{"id": "P1", "title": "P1", "status": "pending",
                    "ado": {"id": 501}, "adoParent": {"id": 500}, "tasks": []},
                   {"id": "P2", "title": "P2", "status": "pending",
                    "ado": {"id": 500}, "adoParent": {"id": 501}, "tasks": []}])
    _f, _w = M._check_ado_parents(_loop, _loop["phases"])
    check("ap30 a declared loop between two phases is a FINDING once per phase "
          "- offline, with no meta.ado.hierarchy in that manifest at all, "
          "because the structural tier stands on the manifest's own ids: %r"
          % (_f,), len(_f) == 2 and _w == [])
    check("ap31 ...and it reaches every consumer through `validate()`, not "
          "only a direct caller: %r"
          % ([x for x in _rules.validate(_loop)[0]
              if "the other's work item" in x],),
          len([x for x in _rules.validate(_loop)[0]
               if "the other's work item" in x]) == 2)

    _inverted = _plan({"phaseWorkItems": False,
                       "types": {"pbi": "Product Backlog Item"},
                       "hierarchy": {"levels": {"Task": 1,
                                                "Product Backlog Item": 2},
                                     "fetchedAt": "2026-08-24T00:00:00Z",
                                     "basis": "captured for this case"}},
                      [{"id": "P1", "title": "P1", "status": "pending",
                        "ado": {"id": 800},
                        "adoParent": {"id": 41, "type": "Task"}, "tasks": []}])
    _f, _w = M._check_ado_parents(_inverted, _inverted["phases"])
    check("ap32 an INVERTED backlog rank is a WARNING and never a finding - the "
          "ranks are a cache with a fetchedAt, and 41 is not an id this "
          "manifest carries, so nothing structural can explain this: %r"
          % ((_f, _w),),
          _f == [] and len(_w) == 1 and "rank" in _w[0])
    check("ap33 ...so `validate()` still calls that manifest VALID, which is "
          "what keeps a month-old cache from reddening somebody's CI: %r"
          % (_rules.validate(_inverted)[0],),
          _rules.validate(_inverted)[0] == [])
    # The second direction. A check that fired unconditionally would light up
    # here too, and every case above would still pass.
    _fine = _plan({"phaseWorkItems": False, "parentWorkItem": 41,
                   "types": {"pbi": "Product Backlog Item"},
                   "hierarchy": {"levels": {"Task": 1,
                                            "Product Backlog Item": 2,
                                            "Feature": 3},
                                 "fetchedAt": "2026-08-24T00:00:00Z",
                                 "basis": "captured for this case"}},
                  [{"id": "P1", "title": "P1", "status": "pending",
                    "ado": {"id": 800},
                    "adoParent": {"id": 41, "type": "Feature"}, "tasks": []}])
    check("ap34 a legitimate parent produces no finding and no warning at all: "
          "%r" % (M._check_ado_parents(_fine, _fine["phases"]),),
          M._check_ado_parents(_fine, _fine["phases"]) == ([], []))
    check("ap35 ...and NOT VERIFIED is silent HERE and only here: validate() "
          "runs on every manifest write, so a line per link saying the ranks "
          "were never fetched would arrive hundreds of times and teach people "
          "to skip warnings. It is counted and printed where the decision is "
          "made instead: %r"
          % (M._check_ado_parents(_plan({"phaseWorkItems": False},
                                        _fine["phases"]),
                                  _fine["phases"]),),
          M._check_ado_parents(_plan({"phaseWorkItems": False},
                                     _fine["phases"]),
                               _fine["phases"]) == ([], []))
    check("ap36 a manifest with no meta.ado at all is not asked the question, "
          "because there is no board for anything to hang on",
          M._check_ado_parents({"meta": {}}, _fine["phases"]) == ([], []))

    # --- the compatibility split, both directions -----------------------------
    # THE SAME BROKEN BOARD, written two ways. A manifest that predates
    # `adoParent` can describe a loop through `meta.ado.parentWorkItem` alone,
    # and COMPATIBILITY.md promises a file that validates keeps validating - so
    # this one WARNS and stays valid, while the authored spelling is a finding.
    _inherited = _plan({"parentWorkItem": 31},
                       [{"id": "P1", "title": "P1", "status": "pending",
                         "ado": {"id": 30},
                         "tasks": [{"id": "P1.1", "title": "t",
                                    "status": "pending",
                                    "ado": {"id": 31}}]}])
    _f, _w = M._check_ado_parents(_inherited, _inherited["phases"])
    check("ap39 a loop inherited from meta.ado.parentWorkItem alone is WARNED "
          "about, once per member, and is NOT a finding - no adoParent is "
          "involved, so this file could have been written before the key "
          "existed: %r" % ((_f, _w),),
          _f == [] and len([x for x in _w if "loop" in x]) == 2)
    check("ap40 ...so `validate()` still calls that manifest VALID, which is "
          "the promise: a file that validates against a release keeps "
          "validating against every later one in the major line: %r"
          % (_rules.validate(_inherited)[0],),
          _rules.validate(_inherited)[0] == [])
    # The other direction, on the SAME shape: only the spelling of the parent
    # changes. A rule that always warned would pass ap39 and fail here.
    _authored = _plan({},
                      [{"id": "P1", "title": "P1", "status": "pending",
                        "ado": {"id": 30}, "adoParent": {"id": 31},
                        "tasks": [{"id": "P1.1", "title": "t",
                                   "status": "pending",
                                   "ado": {"id": 31}}]}])
    _f, _w = M._check_ado_parents(_authored, _authored["phases"])
    check("ap41 ...and the same loop written as an adoParent IS a finding, "
          "once per member - refusing a key no older manifest can carry is "
          "fully additive: %r" % (_f,),
          len(_f) == 2 and [x for x in _w if "loop" in x] == [])
    check("ap42 ...so `validate()` calls THAT manifest invalid, which is the "
          "case that fails if the split ever collapses to 'always warn': %r"
          % (len(_rules.validate(_authored)[0]),),
          len([x for x in _rules.validate(_authored)[0] if "loop" in x]) == 2)

    # --- requireParent, graded against the plan rather than a hunch -----------
    _homeless = _plan({"phaseWorkItems": False,
                       "conventions": {"requireParent": True}},
                      [{"id": "P1", "title": "P1", "status": "pending",
                        "adoParent": {"id": 41}, "tasks": []},
                       {"id": "P2", "title": "P2", "status": "pending",
                        "tasks": []}])
    _f, _w = M._check_ado_parents(_homeless, _homeless["phases"])
    check("ap37 requireParent names the item that really has nowhere to go and "
          "not the one that declared a parent - the manifest-aware half of the "
          "warning `_manifest_ado` gave up when an absent parentWorkItem "
          "stopped meaning anything: %r" % (_w,),
          _f == [] and len([x for x in _w if "requireParent" in x]) == 1
          and "P2" in _w[-1] and "P1" not in _w[-1])
    _covered = _plan({"phaseWorkItems": False,
                      "conventions": {"requireParent": True}},
                     [{"id": "P1", "title": "P1", "status": "pending",
                       "adoParent": {"id": 41}, "tasks": []},
                      {"id": "P2", "title": "P2", "status": "pending",
                       "adoParent": {"id": 42}, "tasks": []}])
    check("ap38 ...and a plan where every phase declares one is SILENT, with "
          "no meta.ado.parentWorkItem anywhere - the config the old blanket "
          "warning called broken: %r"
          % (M._check_ado_parents(_covered, _covered["phases"]),),
          M._check_ado_parents(_covered, _covered["phases"]) == ([], []))

    # --- F120: the board demands what the connector cannot supply -------------
    # `_covered` is the fixture on purpose: every phase declares its own parent,
    # so `_require_parent_warnings` is silent over it and any warning below is
    # the BUG one and not that one leaking. Push creates a bug card with no
    # parent link at all, so on this board those creates were refused at push
    # time and the validator - whose inventory call deliberately omits bugs -
    # could not see it coming.
    def _withbugs(plan, bugs):
        out = dict(plan)
        out["bugs"] = bugs
        return out

    _bugged = _withbugs(_covered, [{"id": "BUG-1", "title": "x", "status": "open"},
                                   {"id": "BUG-2", "title": "y", "status": "open",
                                    "ado": {"id": 900}}])
    _f, _w = M._check_ado_parents(_bugged, _bugged["phases"])
    # Joined rather than indexed, here and below. A mutation that stops the
    # warning firing leaves this list EMPTY, and `_w[-1]` would raise inside the
    # case rather than failing it - taking every case after this one, and their
    # unprinted output, down with it. That happened while proving these red.
    _said = "".join(_w)
    check("ap43 requireParent draws a warning about the UNLINKED bug and names "
          "it, because a push would create that card outside the backlog this "
          "board requires everything to sit in: %r" % (_w,),
          _f == [] and len([x for x in _w if "requireParent" in x]) == 1
          and "BUG-1" in _said)
    check("ap44 ...and NOT about the linked one, which a push only ever "
          "UPDATES - the same reason its neighbour is a warning rather than a "
          "finding, applied to which items it counts: %r" % (_said[-90:],),
          "BUG-1" in _said and "BUG-2" not in _said)
    check("ap45 ...as a WARNING, so validate() still calls that manifest VALID "
          "- a board whose standard this connector cannot fully meet is a gap "
          "to report before the push, not a file to refuse: %r"
          % (_rules.validate(_bugged)[0],),
          _rules.validate(_bugged)[0] == []
          and len([x for x in _rules.validate(_bugged)[1]
                   if "not linked yet" in x]) == 1)
    # THE SECOND DIRECTION, twice. A check that fired unconditionally would
    # light up on both of these and every case above would still pass.
    _all_linked = _withbugs(_covered, [{"id": "BUG-1", "title": "x",
                                        "status": "open", "ado": {"id": 901}}])
    check("ap46 a plan whose bugs are ALL linked is silent, because nothing is "
          "about to be created without a parent on their account: %r"
          % (M._check_ado_parents(_all_linked, _all_linked["phases"]),),
          M._check_ado_parents(_all_linked, _all_linked["phases"]) == ([], []))
    _no_rule = _withbugs(
        _plan({"phaseWorkItems": False}, _covered["phases"]),
        [{"id": "BUG-1", "title": "x", "status": "open"}])
    check("ap47 ...and so is the SAME unlinked bug on a board that never asked "
          "for a parent - the warning is about the board's rule, not about a "
          "bug having no parent, which is normal: %r"
          % (M._check_ado_parents(_no_rule, _no_rule["phases"]),),
          M._check_ado_parents(_no_rule, _no_rule["phases"]) == ([], []))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_crossrefs.py --selftest\n")
    raise SystemExit(2)
