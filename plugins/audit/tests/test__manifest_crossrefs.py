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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_crossrefs.py --selftest\n")
    raise SystemExit(2)
