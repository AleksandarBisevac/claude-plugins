#!/usr/bin/env python3
"""
The cases for `_panel_composition.py` - the plan as the panel shows it:
phase/task rows, bug rows, the ADO honesty banner and the areas registry.

Moved out of `test__panel_state.py` at U3.1, with the code it covers. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _panel_paths as _paths                     # noqa: E402  (the shared base)
import _ado_parent as _adop                    # noqa: E402  (the marker + resolve)
import _ado_tracked as _adot               # noqa: E402  (the three-valued answer + its basis)
import _ado_drift as _drift                    # noqa: E402  (link_inventory: the walk the banner counts)
import _loader                                 # noqa: E402  (read-ado-links.py + run-test-gate.py are entry points; only a load reaches them)
import _evidence_io as _evidence           # noqa: E402  (where the run ledger lives, for the fixture)
import _panel_composition as M      # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import json
    import pathlib                                 # noqa: F401  (used by moved cases)
    import re
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer -- straight through `_manifest_io`,
        the implementation panel-server's `_atomic_write_json` delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-composition-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_paths._config_path(proj), {"trivialLineThreshold": 40})
    mpath = _paths._manifest_path(proj, _paths.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    check("_areas_of normalizes string/list/absent",
          M._areas_of("x") == ["x"] and M._areas_of(["a", "b"]) == ["a", "b"]
          and M._areas_of(None) == [])
    # --- v0.37 B1: the three skill states, as the panel payload carries them ----
    # Explicit null is an ANSWER ("none applies" — it stops the area fallback)
    # and the view must ship it AS null; flattening it to [] made the opt-out
    # indistinguishable from "unconsidered" on every panel surface.
    check("_skills_of keeps the three states apart: null stays None, absent "
          "and junk read as []",
          M._skills_of({"skills": None}) is None
          and M._skills_of({}) == []
          and M._skills_of({"skills": "x"}) == []
          and M._skills_of({"skills": ["a"]}) == ["a"])
    _cv3 = M._composition_view({
        "meta": {"areas": {"api": {"root": "src", "skills": ["conv", "sec"]},
                           "web": {"root": "w", "skills": ["conv"]}}},
        "phases": [{"id": "PX", "title": "p", "status": "pending",
                    "tasks": [{"id": "PX.1", "title": "t", "status": "pending",
                               "skills": None}]}]})
    check("the composition view ships the opt-out as null, not as []",
          _cv3["tasks"][0]["skills"] is None)
    check("...and carries the area-declared skill names, deduped, so the "
          "client's inventory hint sees every name the manifest spells",
          _cv3.get("areaSkills") == ["conv", "sec"])

    # --- connector v2: the ADO card's read side ---------------------------------
    # adoStatus is MANIFEST EVIDENCE only (links /audit:sync wrote) — the panel
    # reports what the file proves, never what the connector claims; the policy
    # tab's rule, applied to a second feature. No network in the panel, ever.
    check("the composition view ships meta.ado verbatim - the card's form source",
          M._composition_view({"meta": {"ado": {"organization": "o"}},
                             "phases": []})["meta"]["ado"]
          == {"organization": "o"})
    _as1 = M._ado_status({"meta": {}, "phases": []})
    # The KEY SET is asserted and not just the values it holds: a key added to
    # this payload with no case of its own would otherwise ship unrendered and
    # unexplained, which is how a key nothing draws becomes noise.
    check("adoStatus: an unconfigured manifest reads configured=false, "
          "nothing linked, no effective switches - and the shape is exactly "
          "these keys: %r" % (sorted(_as1),),
          _as1["configured"] is False and _as1["enabled"] is False
          and _as1["echo"] is False and _as1["lastSyncedAt"] is None
          and _as1["linked"] == {"tasks": 0, "bugs": 0, "phases": 0}
          and sorted(_as1) == ["configured", "echo", "enabled", "lastSyncedAt",
                               "linked", "shared"])
    _as2 = M._ado_status({"meta": {"ado": {"organization": "o",
                                         "enabled": False}}, "phases": []})
    check("adoStatus: enabled:false reads off (echo effectively off too) "
          "while staying configured",
          _as2["configured"] is True and _as2["enabled"] is False
          and _as2["echo"] is False)
    _as3 = M._ado_status({"meta": {"ado": {"organization": "o"}}, "phases": []})
    check("adoStatus: absent switches read as their defaults - enabled on, "
          "echo on",
          _as3["configured"] is True and _as3["enabled"] is True
          and _as3["echo"] is True
          and _as3["linked"] == {"tasks": 0, "bugs": 0, "phases": 0})
    _as4 = M._ado_status({
        "meta": {"ado": {"organization": "o", "echo": False}},
        "phases": [{"id": "P1", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-02T00:00:00Z"},
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "ado": {"id": 7,
                                       "lastSyncedAt": "2026-08-03T00:00:00Z"}},
                              {"id": "P1.2", "title": "t", "status": "pending",
                               "ado": "junk"}]}],
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open",
                  "ado": {"id": 8, "lastSyncedAt": "2026-08-01T00:00:00Z"}},
                 {"id": "BUG-2", "title": "b", "status": "open",
                  "ado": {"id": "x"}}]})
    check("adoStatus: linked counts by kind with junk shapes skipped "
          "(int ids only), the newest lastSyncedAt wins, echo:false honoured",
          _as4["linked"] == {"tasks": 1, "bugs": 1, "phases": 1}
          and _as4["lastSyncedAt"] == "2026-08-03T00:00:00Z"
          and _as4["echo"] is False and _as4["enabled"] is True)
    check("the composition view carries adoStatus (and a manifest with no "
          "meta.ado still gets the full shape)",
          M._composition_view({"meta": {}, "phases": []})
          .get("adoStatus", {}).get("configured") is False)
    # _as5 pins why the phase half of this walk is NOT `_mio.iter_tasks`: a phase
    # /audit:sync has pushed but nobody has broken into tasks yet still carries a
    # link and a timestamp, and `iter_tasks` yields nothing at all for it. The
    # fixture puts the NEWEST timestamp on that phase so a version that dropped it
    # gets both the count AND lastSyncedAt wrong — a same-or-older stamp there
    # would let the two versions agree on the second half by accident.
    _as5 = M._ado_status({
        "meta": {"ado": {"organization": "o"}},
        "phases": [{"id": "P1", "title": "linked, no tasks yet",
                    "status": "pending",
                    "ado": {"id": 4, "lastSyncedAt": "2026-08-09T00:00:00Z"}},
                   {"id": "P2", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-01T00:00:00Z"},
                    "tasks": [
                       {"id": "P2.1", "title": "t", "status": "pending",
                        "ado": {"id": 5,
                                "lastSyncedAt": "2026-08-04T00:00:00Z"}}]}]})
    check("adoStatus: a phase with a link and NO tasks is still counted, and "
          "still wins lastSyncedAt",
          _as5["linked"] == {"tasks": 1, "bugs": 0, "phases": 2}
          and _as5["lastSyncedAt"] == "2026-08-09T00:00:00Z")

    # --- the banner counts the DOOR's walk, not a second one -------------------
    # `_ado_status` used to walk phases, `_mio.iter_tasks` and bugs itself, with
    # its own copy of the int-and-not-bool id guard - the same walk
    # `_ado_drift.link_inventory` already performs for `read-ado-links.py` and
    # for /audit:doctor's `ado links` row. Two walks over one file is two answers
    # waiting to disagree, and these are the cases that would see them disagree.
    _lk_manifest = {
        "meta": {"ado": {"organization": "o"}},
        "phases": [{"id": "P1", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-02T00:00:00Z"},
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "ado": {"id": 7,
                                       "lastSyncedAt": "2026-08-03T00:00:00Z"}},
                              # A bool id is the F15 shape the validator holds:
                              # `True` is an int in Python and would count as a
                              # work item id anywhere the guard is written as
                              # `isinstance(x, int)` alone.
                              {"id": "P1.2", "title": "t", "status": "pending",
                               "ado": {"id": True}}]}],
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open",
                  "ado": {"id": 8, "lastSyncedAt": "2026-08-01T00:00:00Z"}}]}
    # THE TRANSLATION TABLE IS PINNED AGAINST THE DOOR'S OWN VOCABULARY FIRST,
    # read off `_ado_drift`'s source rather than off the rows a fixture happened
    # to produce: a fourth kind added there and not here would otherwise reach a
    # payload key nobody renders, and no fixture in this file would show it. It
    # runs BEFORE the count case because the count case indexes that table, and
    # a suite that dies indexing it teaches nothing about why.
    _lk_src = _harness.module_source(_drift)
    _lk_kinds = sorted(set(re.findall(r'_collect\(out, "([a-z]+)"', _lk_src)))
    check("ac_lk1 every kind `link_inventory` can emit has a cell in "
          "`_LINK_COUNT_KEY`, matched EXACTLY so a retired kind is caught too - "
          "an empty scan is a failure here and not a clean bill: %r"
          % ((_lk_kinds, sorted(M._LINK_COUNT_KEY)),),
          _lk_kinds == sorted(M._LINK_COUNT_KEY) and len(_lk_kinds) == 3)
    _lk_rows = _drift.link_inventory(_lk_manifest)
    _lk_status = M._ado_status(_lk_manifest)
    _lk_expect = {"tasks": 0, "bugs": 0, "phases": 0}
    for _r in _lk_rows:
        # `.get(kind, kind)` mirrors the module rather than re-deciding: an
        # unmapped kind must land in its own cell on BOTH sides, so what tells a
        # broken table apart is the literal below and not a KeyError here.
        _lk_key = M._LINK_COUNT_KEY.get(_r["kind"], _r["kind"])
        _lk_expect[_lk_key] = _lk_expect.get(_lk_key, 0) + 1
    check("ac_lk2 ...and the banner's counts ARE that inventory, kind for kind: "
          "a manifest carrying all three kinds plus a bool id, so a second walk "
          "that dropped a kind or admitted `True` disagrees here rather than on "
          "somebody's card: %r" % ((_lk_status["linked"], _lk_expect),),
          _lk_status["linked"] == _lk_expect
          and _lk_expect == {"tasks": 1, "bugs": 1, "phases": 1}
          and len(_lk_rows) == 3)
    # THE SECOND DIRECTION, and it reads vacuous on purpose: it is the only case
    # that fails if a kind with no cell is quietly folded into a neighbour, which
    # would inflate a number the operator reads as evidence.
    _lk_odd = M._ado_status({"meta": {"ado": {}}, "phases": [],
                             "bugs": []})
    check("ac_lk3 a manifest with nothing linked still reports all three cells "
          "at zero rather than an empty map - a count that appears only when it "
          "is non-zero cannot be told from a count nobody took: %r"
          % (_lk_odd["linked"],),
          _lk_odd["linked"] == {"tasks": 0, "bugs": 0, "phases": 0})

    # --- F147: the work items MORE THAN ONE manifest item claims --------------
    # Nothing validates that a work-item id is claimed once, so a push writes
    # every claimant to the same card and the last one wins. Grouping the walk
    # the banner already does is the only place that fact is available offline.
    # The fixture puts THREE kinds on one id and a second, unshared id beside
    # it, so a version that grouped only within a kind, or that reported every
    # id it saw, disagrees here rather than on somebody's board.
    _sh_manifest = {
        "meta": {"ado": {"organization": "o"}},
        "phases": [{"id": "P1", "title": "p", "status": "pending",
                    "ado": {"id": 12},
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "ado": {"id": 12}},
                              {"id": "P1.2", "title": "t", "status": "pending",
                               "ado": {"id": 30}}]}],
        "bugs": [{"id": "BUG-2", "title": "b", "status": "open",
                  "ado": {"id": 12}}]}
    _sh = M._ado_status(_sh_manifest)["shared"]
    check("sc1 a work item three items claim is named once, with every "
          "claimant on it, and the id claimed by ONE is not in the list - a "
          "grouping that reported every id it saw would pass a presence "
          "assertion and fail this: %r" % (_sh["items"],),
          _sh["state"] == "shared" and len(_sh["items"]) == 1
          and _sh["items"][0] == {"adoId": 12,
                                  "claimants": ["phase P1", "task P1.1",
                                                "bug BUG-2"]})
    check("sc2 ...and the banner's own claim carries the ids under it plus the "
          "command that re-derives them, so the number is checkable rather "
          "than believed: %r" % (_sh["basis"],),
          "#12" in _sh["basis"] and "#30" not in _sh["basis"]
          and M._LINKS_LENS in _sh["basis"]
          and _sh["refresh"] == M._LINKS_LENS)
    # THE TWO EMPTIES, WHICH ARE THE WHOLE REASON THIS IS A STATE AND NOT A
    # LIST. A plan with links and no collision and a plan with no links at all
    # both hand a banner zero rows; rendering them the same says "every card is
    # claimed once" over a plan where nothing was ever counted.
    _sh_clean = M._ado_status(_lk_manifest)["shared"]
    _sh_none = M._ado_status({"meta": {"ado": {}}, "phases": [], "bugs": []})["shared"]
    check("sc3 links walked with no collision reads `none` and links never "
          "walked reads `unlinked` - two states, two sentences, and neither "
          "borrows the other's: %r vs %r"
          % (_sh_clean["state"], _sh_none["state"]),
          _sh_clean["state"] == "none" and _sh_none["state"] == "unlinked"
          and _sh_clean["items"] == [] and _sh_none["items"] == []
          and _sh_clean["basis"] != _sh_none["basis"]
          and "nothing has been counted" in _sh_none["basis"]
          and "exactly one" in _sh_clean["basis"])
    # `read-ado-links.py` groups its own rows the same way for the `SHARED:`
    # lines /audit:sync status prints. It is an entry point and cannot be
    # imported, so the grouping lives twice - and a duplication nothing compares
    # is the one that drifts. This is the comparison.
    _sh_links = _loader.load_script("read-ado-links.py",
                                    modname="pc_read_ado_links")
    _sh_theirs = _sh_links.claims_shared_by_several(
        _sh_links.manifest_side(_sh_manifest)["rows"])
    check("sc4 the panel's grouping and `read-ado-links.claims_shared_by_"
          "several` answer identically over one manifest - same ids, same "
          "claimants, same order: %r vs %r" % (_sh["items"], _sh_theirs),
          [(e["adoId"], e["claimants"]) for e in _sh["items"]]
          == [(e["adoId"], e["claimants"]) for e in _sh_theirs]
          and len(_sh_theirs) == 1)

    # --- connector v2: where ONE phase hangs, as the panel payload carries it ---
    # THE THREE STORED STATES REACH THE CONTROL AS THREE VALUES. Absent is an
    # answer ("use the fallback"), null is a different answer ("hangs under
    # nothing on purpose"), and a declaration is a third - so the payload spells
    # absent with `_ado_parent`'s own marker rather than leaving the key off and
    # asking the browser to guess which of the two it was looking at.
    _ap_ado = {"organization": "o", "parentWorkItem": 41,
               "parentCandidates": {
                   "items": [{"id": 41, "type": "Feature", "title": "Checkout",
                              "state": "Active", "url": "https://x/41"},
                             {"id": "junk"}],
                   "fetchedAt": "2026-08-20T00:00:00Z",
                   "basis": "WIQL over Feature, Epic scoped to Area\\Web"}}
    _apv = M._composition_view({
        "meta": {"ado": _ap_ado},
        "phases": [{"id": "P1", "title": "declared", "status": "pending",
                    "adoParent": {"id": 55, "type": "Feature",
                                  "title": "Payments"}},
                   {"id": "P2", "title": "nowhere", "status": "pending",
                    "adoParent": None},
                   {"id": "P3", "title": "silent", "status": "pending"}]})
    _ap_rows = dict((r["id"], r) for r in _apv["phases"])
    check("ap1 a declared adoParent reaches the phase row VERBATIM - the basis "
          "travels with the id, because a control that offered only the number "
          "would drop what makes the number checkable",
          _ap_rows["P1"]["adoParent"] == {"id": 55, "type": "Feature",
                                          "title": "Payments"},
          repr(_ap_rows["P1"].get("adoParent")))
    check("ap2 an explicit null reaches the row AS null, and an ABSENT key "
          "reaches it as the use-fallback marker - two different answers, and "
          "a payload that spelled both `null` would make the control unable to "
          "tell them apart",
          _ap_rows["P2"]["adoParent"] is None
          and _ap_rows["P3"]["adoParent"] == _adop.use_fallback(),
          repr((_ap_rows["P2"].get("adoParent"),
                _ap_rows["P3"].get("adoParent"))))
    check("ap3 every phase row carries the RESOLUTION beside the declaration, "
          "and it comes from `_ado_parent.resolve` - the one function every "
          "other surface asks, so the panel cannot hold a second opinion about "
          "where a phase hangs",
          # .get throughout: the mutation these cases are for DROPS a key, and
          # a KeyError would abort the suite and take every later case's output
          # with it instead of naming the one thing that broke.
          _ap_rows["P1"]["adoParentResolved"].get("id") == 55
          and _ap_rows["P1"]["adoParentResolved"].get("source") == "item"
          and _ap_rows["P2"]["adoParentResolved"].get("id") is None
          and _ap_rows["P2"]["adoParentResolved"].get("source") == "item"
          and _ap_rows["P3"]["adoParentResolved"].get("id") == 41
          and _ap_rows["P3"]["adoParentResolved"].get("source") == "meta"
          and _adop.resolve({"id": "P3"}, _ap_ado)["basis"]
          == _ap_rows["P3"]["adoParentResolved"].get("basis"),
          repr(_ap_rows["P3"].get("adoParentResolved")))
    check("ap4 ...and the resolution is the WHOLE answer or none of it: the "
          "basis rides along, because an id with no sentence behind it is the "
          "claim without the thing that makes it checkable",
          sorted(_ap_rows["P1"]["adoParentResolved"]) == ["basis", "id",
                                                          "source"],
          repr(sorted(_ap_rows["P1"]["adoParentResolved"])))
    _app = _apv["adoParents"]
    # THE INPUTS THAT TELL THE TWO IMPLEMENTATIONS APART. On a usable integer a
    # re-read of `parentWorkItem` gives the same answer `resolve` does, so a
    # case built only on that would pass either way - it was written that way
    # first and a mutation survived it. `resolve` refuses a non-positive or
    # non-integer id (`_positive_id`, which refuses bool before int) and reports
    # source `none`; a re-read hands the junk straight to the control and calls
    # it `meta`.
    _app_junk = [M._composition_view({"meta": {"ado": {"parentWorkItem": _bad}},
                                      "phases": []})["adoParents"]["fallback"]
                 for _bad in ("41", 0, -3, True, None)]
    _app_off = M._composition_view({"meta": {}, "phases": []})["adoParents"]
    check("ap5 the fallback the control has to NAME comes from `resolve`, never "
          "from a second read of parentWorkItem - so an id the resolver refuses "
          "is offered to nobody, and 'no connector at all' reports source none "
          "rather than a meta fallback of None: %r" % (_app_junk,),
          _app["fallback"] == {"id": 41, "source": "meta"}
          and _app_junk == [{"id": None, "source": "none"}] * len(_app_junk)
          and _app_off["fallback"] == {"id": None, "source": "none"},
          repr((_app, _app_off["fallback"])))
    check("ap6 the cached candidates ride the same payload, junk id dropped, "
          "with the fetch's own moment and the query that scoped it - a cache "
          "with no moment cannot be aged and one with no basis has to be "
          "trusted rather than checked",
          [c["id"] for c in _app["candidates"]] == [41]
          and _app["candidates"][0]["title"] == "Checkout"
          and _app["fetchedAt"] == "2026-08-20T00:00:00Z"
          and _app["cache"] == "items"
          and ("Scoped by: WIQL over Feature, Epic scoped to Area\\Web."
               in _app["basis"]),
          repr(_app))
    _app_absent = M._composition_view({"meta": {"ado": {"organization": "o"}},
                                       "phases": []})["adoParents"]
    _app_empty = M._composition_view({
        "meta": {"ado": {"organization": "o",
                         "parentCandidates": {
                             "items": [],
                             "fetchedAt": "2026-08-20T00:00:00Z",
                             "basis": "WIQL over Feature scoped to Area\\Web"}}},
        "phases": []})["adoParents"]
    check("ap7 AN ABSENT CACHE IS NOT AN EMPTY ONE. Nobody has asked this board "
          "yet; a bare empty list would say the board has no parent-shaped item "
          "on it, which is the filter-narrowed-to-nothing reading as all-clear. "
          "So the state is named and the sentence says which it is",
          _app_absent["cache"] == "absent"
          and _app_absent["candidates"] == []
          and _app_absent["fetchedAt"] is None
          and "nobody has asked" in _app_absent["basis"]
          and _app_absent["refresh"] == "/audit:sync parents",
          repr(_app_absent))
    check("ap8 ...and an EMPTY cache says the other thing: somebody looked, at "
          "a moment, with a query that is named - so an empty list can be told "
          "from an unfiltered one, which is the whole reason the fetch writes a "
          "basis",
          _app_empty["cache"] == "empty"
          and _app_empty["fetchedAt"] == "2026-08-20T00:00:00Z"
          and "Area\\Web" in _app_empty["basis"]
          and _app_absent["basis"] != _app_empty["basis"],
          repr(_app_empty))
    check("ap9 a cache the manifest carries with NO basis says so rather than "
          "printing an empty sentence - a basis that is missing is the thing to "
          "say, never a default to fill the gap with",
          "no basis" in M._composition_view({
              "meta": {"ado": {"parentCandidates": {"items": []}}},
              "phases": []})["adoParents"]["basis"],
          repr(M._composition_view({
              "meta": {"ado": {"parentCandidates": {"items": []}}},
              "phases": []})["adoParents"]["basis"]))

    # --- F101: and what the BOARD says, which the row used to leave out --------
    # THE DEFECT WAS TWO FACTS PAINTING ONE CELL. Both values above are read out
    # of the manifest, so a phase the board agrees with and a phase nobody has
    # ever compared were the same pixels - and on the board this was found on,
    # the one that "agreed" agreed with a declaration a panel save had written
    # hours earlier. These cases hold the three answers apart, and the fixture
    # ids differ from the link ids on purpose: a case where #121 declares #121
    # could not tell an observation from a declaration.
    _bp_unlinked = M._board_parent({"id": "P1"})
    _bp_silent = M._board_parent({"id": "P2", "ado": {"id": 121}})
    _bp_declared = M._board_parent(
        {"id": "P3", "ado": {"id": 121},
         "adoParent": {"id": 101, "source": "declared",
                       "observedAt": "2026-08-24T09:00:00Z"}})
    _bp_observed = M._board_parent(
        {"id": "P4", "ado": {"id": 121},
         "adoParent": {"id": 101, "source": "imported",
                       "observedAt": "2026-08-24T09:00:00Z"}})
    check("bp1 a phase with NO work item reports `unlinked` rather than a "
          "missing board answer: nothing of it is on the board, so nothing on "
          "the board hangs anywhere and the declaration beside it is a plan "
          "for a create: %r" % (_bp_unlinked["state"],),
          _bp_unlinked["state"] == "unlinked" and _bp_unlinked["id"] is None,
          repr(_bp_unlinked))
    check("bp2 a LINKED phase nobody has compared reports `never-asked`, names "
          "the work item it is about, and carries the command that would ask - "
          "this is the state the cell used to render as agreement",
          _bp_silent["state"] == "never-asked"
          and _bp_silent["id"] is None
          and "#121" in _bp_silent["basis"]
          and M._PARENT_OBSERVE in _bp_silent["basis"],
          repr(_bp_silent))
    # THE SECOND DIRECTION, and the whole fault in one line: a phase that
    # DECLARES #101 is in exactly the same board state as one that declares
    # nothing, because nobody asked either way. A reader that let a declaration
    # stand in for an observation would pass bp2 and fail here.
    check("bp3 ...and a phase that DOES declare a parent is in that same state, "
          "because a declaration is not an observation - `source: declared` is "
          "somebody typing, and the board was still never asked: %r"
          % (_bp_declared["state"],),
          _bp_declared["state"] == "never-asked"
          and _bp_declared["id"] is None
          and _bp_declared["basis"] == _bp_silent["basis"].replace("P2", "P3"),
          repr(_bp_declared))
    check("bp4 only an IMPORTED declaration is an observation, and it is "
          "reported as the record of a moment: the id AND the moment ride the "
          "block, because an observation with no `when` cannot be aged",
          _bp_observed["state"] == "observed"
          and _bp_observed["id"] == 101
          and _bp_observed["observedAt"] == "2026-08-24T09:00:00Z"
          and "2026-08-24T09:00:00Z" in _bp_observed["basis"],
          repr(_bp_observed))
    _bp_junk = M._board_parent({"id": "P5", "ado": {"id": 121},
                                "adoParent": {"id": "101",
                                              "source": "imported"}})
    check("bp5 an imported declaration whose id is UNUSABLE is not an "
          "observation: a pull wrote nothing readable, and reporting it as "
          "what the board said would be the claim without the basis that makes "
          "it true: %r" % (_bp_junk["state"],),
          _bp_junk["state"] == "never-asked" and _bp_junk["id"] is None,
          repr(_bp_junk))
    _bp_all = [_bp_unlinked, _bp_silent, _bp_observed]
    check("bp6 the three states' sentences are three DIFFERENT sentences - the "
          "fault being fixed is two answers reading alike, so a state that "
          "borrowed a neighbour's wording would be that fault again with more "
          "code: %r" % ([b["state"] for b in _bp_all],),
          len(set(b["basis"] for b in _bp_all)) == len(_bp_all)
          and all(b["basis"] for b in _bp_all))
    check("bp7 every state points at the command that ASKS the board, and it "
          "is not the one that refreshes the candidate cache: `parents` writes "
          "meta.ado only and touches no item's own link, so a reader sent "
          "there would run a command that cannot answer this: %r"
          % (M._PARENT_OBSERVE,),
          M._PARENT_OBSERVE != M._PARENT_REFRESH
          and set(b["refresh"] for b in _bp_all) == set([M._PARENT_OBSERVE]))
    _bp_rows = M._composition_view({
        "meta": {"ado": _ap_ado},
        "phases": [{"id": "P1", "title": "unlinked", "status": "pending"},
                   {"id": "P2", "title": "linked", "status": "pending",
                    "ado": {"id": 121},
                    "adoParent": {"id": 101, "source": "declared"}}]})["phases"]
    check("bp8 the block rides EVERY phase row of /api/state - without that "
          "the panel cannot show any of this, however well the derivation "
          "works, which is the shape F101 was: the answer existed one surface "
          "away and never reached the cell: %r"
          % ([r.get("adoParentBoard", {}).get("state") for r in _bp_rows],),
          # .get throughout, for ap3's reason: the mutation this case is for
          # DROPS the key, and a KeyError would abort the suite and take every
          # later case with it instead of naming the one thing that broke.
          [r.get("adoParentBoard", {}).get("state") for r in _bp_rows]
          == ["unlinked", "never-asked"]
          and sorted(_bp_rows[0].get("adoParentBoard") or {})
          == ["basis", "id", "observedAt", "refresh", "state"],
          repr(_bp_rows[0].get("adoParentBoard")))

    # --- u-board: whether a phase is on the board AT ALL, as the row carries it -
    # THE QUESTION ONE STEP BEFORE `adoParent`, and the three DECLARATION states
    # are not the three ANSWERS: absent and `true` are one answer from two
    # places, and a stored value that is neither boolean is no answer at all.
    # The fixture carries all four inputs so a payload that folded any pair
    # together has a row that tells them apart.
    _at_ado = {"organization": "o"}
    _at_phases = [{"id": "P1", "title": "silent", "status": "pending"},
                  {"id": "P2", "title": "off", "status": "pending",
                   "adoTracked": False},
                  {"id": "P3", "title": "on", "status": "pending",
                   "adoTracked": True},
                  {"id": "P4", "title": "junk", "status": "pending",
                   "adoTracked": "yes"}]
    _at_view = M._composition_view({"meta": {"ado": _at_ado},
                                    "phases": _at_phases})
    _at_rows = dict((r.get("id"), r) for r in _at_view["phases"])
    check("at1 the DECLARATION reaches the row in all four of its shapes, and "
          "`null` is the absence of one: the schema types this field boolean, "
          "so null is not a value it can carry and needs no marker - which is "
          "the one way it differs from adoParent, where null IS a value: %r"
          % ([_at_rows.get(p, {}).get("adoTracked") for p in
              ("P1", "P2", "P3", "P4")],),
          _at_rows.get("P1", {}).get("adoTracked") is None
          and _at_rows.get("P2", {}).get("adoTracked") is False
          and _at_rows.get("P3", {}).get("adoTracked") is True
          # VERBATIM, not folded into absent: a payload that flattened this
          # would have the control painting the default over somebody's attempt
          # to keep a phase off a board, which is the one direction that puts
          # work on it.
          and _at_rows.get("P4", {}).get("adoTracked") == "yes",
          repr([_at_rows.get(p, {}).get("adoTracked")
                for p in ("P1", "P2", "P3", "P4")]))
    check("at2 every phase row carries the RESOLUTION beside the declaration, "
          "and it is `_ado_tracked.resolve`'s own answer - the one function the "
          "push plan, the status lens and the door all ask, so the panel cannot "
          "hold a second opinion about what belongs on a shared board",
          # Compared against the module rather than against a literal: a second
          # implementation here would agree with a hand-typed expectation and
          # disagree with the rule the day the rule learns something.
          not [ph for ph in _at_phases
               if _at_rows.get(ph["id"], {}).get("adoTrackedResolved")
               != dict((k, v) for k, v in _adot.resolve(ph, _at_ado).items()
                       if k in ("tracked", "basis"))],
          repr([_at_rows.get(ph["id"], {}).get("adoTrackedResolved")
                for ph in _at_phases]))
    check("at3 `tracked` STAYS THREE-VALUED all the way to the row: True, "
          "False, and None for the declaration nothing can read. A payload that "
          "answered the third one either way would be the false confidence this "
          "key exists to remove, and False is the direction that reads as a "
          "deliberate choice nobody made",
          _at_rows.get("P1", {}).get("adoTrackedResolved", {}).get("tracked")
          is True
          and _at_rows.get("P2", {}).get("adoTrackedResolved", {}).get("tracked")
          is False
          and _at_rows.get("P3", {}).get("adoTrackedResolved", {}).get("tracked")
          is True
          and _at_rows.get("P4", {}).get("adoTrackedResolved", {}).get("tracked")
          is None,
          repr([_at_rows.get(p, {}).get("adoTrackedResolved", {}).get("tracked")
                for p in ("P1", "P2", "P3", "P4")]))
    check("at4 ...and the resolution is the WHOLE answer or none of it: the "
          "basis rides along, and an absent declaration says the default OUT "
          "LOUD in `_ado_tracked`'s own words rather than arriving as a bare "
          "true a reader would take for somebody's choice",
          sorted(_at_rows.get("P1", {}).get("adoTrackedResolved") or {})
          == ["basis", "tracked"]
          and _at_rows.get("P1", {}).get("adoTrackedResolved", {}).get("basis")
          == _adot.DEFAULT_BASIS
          and _adot.FIELD in (_at_rows.get("P2", {})
                              .get("adoTrackedResolved", {}).get("basis") or ""),
          repr((sorted(_at_rows.get("P1", {}).get("adoTrackedResolved") or {}),
                _at_rows.get("P1", {}).get("adoTrackedResolved", {})
                .get("basis"))))
    check("at5 both halves ride EVERY phase row, which is the half that cannot "
          "be derived: the rule can be perfect and the cell still show nothing, "
          "and that IS what F101 was one lever down - the answer existed a "
          "surface away and never reached the row: %r"
          % (sorted(set(tuple(sorted(k for k in r if k.startswith("adoTracked")))
                        for r in _at_view["phases"])),),
          not [r for r in _at_view["phases"]
               if "adoTracked" not in r or "adoTrackedResolved" not in r]
          and len(_at_view["phases"]) == 4,
          repr([sorted(k for k in r if k.startswith("adoTracked"))
                for r in _at_view["phases"][:1]]))
    # THE SHARDED TRAP, and it is the reason this is not a `.get(FIELD)` in the
    # view. On the layout parallel worktrees use, the file at manifestPath is an
    # INDEX whose phases are stubs - `adoTracked` lives in the shard BODY - so a
    # reader that answered off the stub would report a whole plan TRACKED by
    # default. `_ado_tracked` refuses a stub, and the panel gets that refusal
    # only because it asks the module rather than the dict.
    _at_stub = M._composition_view({
        "meta": {"ado": _at_ado},
        "phases": [{"id": "P9", "title": "stub", "status": "pending",
                    "shard": "phases/P9.json"}]})["phases"]
    check("at6 an un-assembled index STUB is reported UNANSWERED and names the "
          "loader, rather than reading 'declares nothing, so tracked' - the "
          "confident wrong answer, on the layout parallel worktrees use",
          [r.get("adoTrackedResolved", {}).get("tracked") for r in _at_stub]
          == [None]
          and "load_manifest" in (_at_stub[:1] or [{}])[0].get(
              "adoTrackedResolved", {}).get("basis", ""),
          repr([r.get("adoTrackedResolved") for r in _at_stub[:1]]))

    # _bugs_view: the bug rows behind the strip. Every derived field is decided in
    # Python by the SAME functions the rollup counts with.
    bm = {"phases": [{"id": "P1", "title": "One", "status": "in_progress", "tasks": [
              {"id": "P1.1", "title": "fix it", "status": "done", "bugId": "BUG-1"},
              {"id": "P1.2", "title": "later", "status": "pending", "bugId": "BUG-2"}]}],
          "bugs": [
              {"id": "BUG-1", "title": "a", "status": "open", "severity": "high",
               "taskId": "P1.1"},
              {"id": "BUG-2", "title": "b", "status": "open", "severity": "critical",
               "taskId": "P1.2"},
              {"id": "BUG-3", "title": "c", "status": "wontfix", "severity": "high"}]}
    bv = M._bugs_view(bm)
    by_id = {b["id"]: b for b in bv}
    check("_bugs_view resolves a bug through its task: fixed when the task is done, "
          "with the stored value kept so it does not read as hand-edited",
          by_id["BUG-1"]["status"] == "fixed" and by_id["BUG-1"]["reported"] == "open"
          and by_id["BUG-2"]["status"] == "open")
    check("_bugs_view names the phase behind the linked task",
          by_id["BUG-1"]["phaseId"] == "P1")
    # A regex in the browser would be a third opinion on 'is this high?' — and the
    # first spelling it would miss is `critical`, which is the one that matters.
    _rup = _paths.status_facts().rollup(bm, [], [])
    check("_bugs_view's open/high agree with the rollup's counts, by construction",
          sum(1 for b in bv if b["open"]) == _rup["bugs"]["open"]
          and sum(1 for b in bv if b["open"] and b["high"])
          == _rup["bugs"]["openHighSeverity"] == 1
          and by_id["BUG-2"]["high"] is True)
    check("_bugs_view on a manifest with no bugs is an empty list, not an error",
          M._bugs_view({"phases": []}) == [])

    # --- v0.28: the areas registry, as GET reports it ---------------------------
    # A sharded fixture on purpose: `meta` lives on the INDEX there, and this
    # endpoint has to read the ASSEMBLED document to see the phases at all.
    _aproj = tempfile.mkdtemp(prefix="state-areas-")
    try:
        _atomic_write_json(M._config_path(_aproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _am = M._manifest_path(_aproj, M.read_config(_aproj))
        os.makedirs(os.path.dirname(_am), exist_ok=True)
        os.makedirs(os.path.join(_aproj, "services", "api"), exist_ok=True)
        _mio.save_sharded(_am, {
            "meta": {"version": 3,
                     "areas": {"api": {"root": "services/api", "description": "d",
                                       "reviewSkill": "backend-review"},
                               "unused": {"root": "services/api"}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "pending", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "apu",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})
        _st = M.areas_state(_aproj)
        # `.get` and not `[...]`: a missing tag is exactly what a broken version of
        # this endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _bytag = {t["tag"]: t for t in _st["tags"]}
        _tag = lambda name: _bytag.get(name) or {}          # noqa: E731
        check("areas GET returns the registry as stored",
              set(_st["areas"]) == {"api", "unused"})
        check("areas GET lists a registered tag with the phases using it",
              _tag("api").get("registered") and _tag("api").get("phases") == ["P1"])
        check("areas GET says a root that exists exists",
              _tag("api").get("rootExists") is True)
        check("areas GET lists a tag no entry covers - the typo case, which "
              "resolves to no reviewer and no skills",
              _tag("apu").get("registered") is False
              and _tag("apu").get("phases") == ["P2"])
        check("areas GET also lists a registered area no phase uses - a rename "
              "done on one side only looks exactly like this",
              _tag("unused").get("registered")
              and _tag("unused").get("phases") == [])
        check("areas GET carries the resolved reviewer of a registered area",
              _tag("api").get("reviewSkill") == "backend-review")
        check("areas GET refuses a manifest path that escapes the project rather "
              "than reading it",
              M.areas_state(os.path.join(_aproj, "nope"))["areas"] == {})
    finally:
        shutil.rmtree(_aproj, ignore_errors=True)

    # --- the ADO card's connection evidence (what /audit:sync connect proved) ---
    def _conn(ado):
        return M._ado_connection({"meta": {"ado": ado}})

    _CONN = {"process": "Scrum", "pbiType": "Product Backlog Item",
             "stateMapNeeded": True, "authPath": "stored",
             "fetchedAt": "2026-08-24T09:00:00Z"}
    _ac_absent = _conn({"organization": "o"})
    _ac_needs = _conn({"connection": dict(_CONN)})
    _ac_ok = _conn({"connection": dict(_CONN),
                    "stateMap": {"task": {"done": "Done"}}})
    _ac_unknown = _conn({"connection": dict(_CONN, process=None,
                                            stateMapNeeded=None)})
    _ac_states = [_ac_absent["state"], _ac_needs["state"], _ac_ok["state"],
                  _ac_unknown["state"]]
    check("ac1 the four ways of knowing something about this board are four "
          "NAMED states, all different - 'never probed', 'probed but the "
          "process is undecidable', 'probed and this board needs a stateMap' "
          "and 'probed, nothing outstanding' are four answers, and a card that "
          "rendered any two alike would say one while meaning the other: %r"
          % (_ac_states,),
          _ac_states == ["absent", "needs-map", "ok", "unknown"]
          and len(set(_ac_states)) == 4)
    _ac_bare = _conn({"connection": {"process": None}})
    check("ac2 ...and their four sentences are all different too, since the "
          "state name never reaches the operator - the sentence does. The "
          "fourth is measured against a block carrying NO moment and NO auth "
          "path, so it is as data-poor as an unprobed board: a version that "
          "collapsed 'never probed' into 'probed, undecidable' would print "
          "one sentence for both, and an earlier form of this case stayed "
          "green through exactly that mutation because its fixture differed "
          "in the data rather than in the branch",
          len(set(r["basis"] for r in (_ac_absent, _ac_needs, _ac_ok,
                                       _ac_unknown))) == 4
          and _ac_bare["state"] == "unknown"
          and _ac_bare["basis"] != _ac_absent["basis"]
          and _ac_bare["basis"].count("access was proven") == 1
          and _ac_absent["basis"].count("access was proven") == 0)
    check("ac3 an unprobed board says the CONNECTOR may still be working and "
          "that what is missing is the evidence - the card must not read an "
          "absent cache as a broken connection, which is the same 'a filter "
          "narrowed to nothing is not all-clear' rule the candidate cache "
          "keeps: %r" % (_ac_absent["basis"][:60],),
          _ac_absent["fetchedAt"] is None
          and _ac_absent["basis"].count("never been probed") == 1
          and _ac_absent["basis"].count("evidence, not the") == 1)
    check("ac4 the needs-map state names the process AND says what will "
          "actually go wrong - a card that only said 'Scrum' leaves the reader "
          "to know the shipped defaults are Agile's",
          _ac_needs["process"] == "Scrum"
          and _ac_needs["basis"].count("stateMap") == 1
          and _ac_needs["basis"].count("refused its state") == 1
          and _ac_ok["basis"].count("refused its state") == 0)
    check("ac5 every state carries the command that re-derives it, so a stale "
          "block can be refreshed rather than believed",
          all(r["refresh"] == "/audit:sync connect"
              for r in (_ac_absent, _ac_needs, _ac_ok, _ac_unknown)))
    check("ac6 the AUTH PATH rides along and is a word naming a MECHANISM - "
          "the panel is a shared screen, and the only useful fact about a 401 "
          "six weeks from now is which KIND of credential lapsed, never whose",
          _ac_ok["authPath"] == "stored"
          and _ac_ok["basis"].count("'stored' auth path") == 1
          and _conn({"connection": dict(_CONN, authPath=None),
                     "stateMap": {}})["basis"].count("not recorded") == 1)
    check("ac7 a probed-but-undecidable board keeps the moment and the auth "
          "path while reporting no process - the stamp is worth keeping on its "
          "own, and inventing a process from it would be the guess this whole "
          "block exists to avoid. The SENTENCE is asserted beside the fields, "
          "because the fields alone survive a collapse into the settled state "
          "untouched: an earlier form of this case stayed green while the card "
          "read 'this board runs the None process'",
          _ac_unknown["process"] is None
          and _ac_unknown["fetchedAt"] == "2026-08-24T09:00:00Z"
          and _ac_unknown["authPath"] == "stored"
          and _ac_unknown["state"] == "unknown"
          and _ac_unknown["basis"].count("could not be told") == 1
          and _ac_unknown["basis"].count("this board runs") == 0
          and _ac_ok["basis"].count("this board runs") == 1)
    check("ac8 a fetchedAt of the wrong TYPE degrades to 'no recorded moment' "
          "rather than being printed as a timestamp - the panel renders what "
          "the manifest holds, and a number formatted as a date is a lie the "
          "card would tell confidently",
          _conn({"connection": dict(_CONN, fetchedAt=1755000000),
                 "stateMap": {}})["fetchedAt"] is None)
    check("ac9 the block rides /api/state's composition payload, beside the "
          "other two ADO blocks - without that the panel cannot show any of "
          "this, however well the derivation works",
          "adoConnection" in M._composition_view(
              {"meta": {"ado": {"connection": dict(_CONN)}}, "phases": []})
          and M._composition_view({"phases": []})["adoConnection"]["state"]
          == "absent")

    # --- test evidence: the pointer, whose gate, and the runs it names ---------
    # THE POINTER IS A CACHE AND THE LEDGER IS THE TRUTH. Everything here holds
    # one of two lines: absent evidence is never a verdict, and an observation
    # nobody made is never a clean one.
    _EV_PTR = {"runId": "r-1", "status": "passed", "at": "2026-08-20T10:00:00Z"}
    _ev_manifest = {
        "meta": {"buildCommands": {"lint": "ruff check ."}},
        "phases": [
            {"id": "P1", "title": "gated", "status": "in_progress",
             "testGate": ["lint"], "testEvidence": dict(_EV_PTR, runId="r-ph"),
             "tasks": [
                 # own gate + own pointer
                 {"id": "P1.1", "title": "a", "status": "done",
                  "tests": {"gate": ["pytest -q"]}, "testEvidence": dict(_EV_PTR)},
                 # no gate of its own: the PHASE's gate is what would grade it,
                 # and no run has been recorded
                 {"id": "P1.2", "title": "b", "status": "pending"},
                 # a gate declared as blank strings is no gate at all
                 {"id": "P1.3", "title": "c", "status": "pending",
                  "tests": {"gate": ["   ", ""]}}]},
            {"id": "P2", "title": "ungated", "status": "pending",
             "testGate": [],
             "tasks": [{"id": "P2.1", "title": "d", "status": "pending"}]}]}
    _ev_view = M._composition_view(_ev_manifest)
    _ev_tasks = dict((t["id"], t) for t in _ev_view["tasks"])
    _ev_phases = dict((p["id"], p) for p in _ev_view["phases"])
    check("ev1 the composition rows carry the pointer VERBATIM and the source of "
          "the gate that would produce it - both, because the pointer alone "
          "cannot tell 'nobody has run this' from 'there is nothing here to "
          "run', and those send a reader to different places",
          _ev_tasks["P1.1"]["testEvidence"] == _EV_PTR
          and _ev_tasks["P1.1"]["gateSource"] == "task"
          and _ev_phases["P1"]["testEvidence"]["runId"] == "r-ph"
          and _ev_phases["P1"]["gateSource"] == "phase",
          repr((_ev_tasks["P1.1"], _ev_phases["P1"]["testEvidence"])))
    check("ev2 ...and an absent pointer is None, never a verdict - while the "
          "gate source beside it STILL says the phase's gate would grade this "
          "task. The negative is the load-bearing half: a payload that filled "
          "the gap with the worst reading of a silence is what the schema "
          "forbids at the field",
          _ev_tasks["P1.2"]["testEvidence"] is None
          and _ev_tasks["P1.2"]["gateSource"] == "phase"
          and _ev_tasks["P1.2"]["status"] == "pending",
          repr(_ev_tasks["P1.2"]))
    check("ev3 a subject nothing could grade says so with a THIRD answer: no "
          "gate on the task, none on its phase, so `gateSource` is None and the "
          "badge reads 'No gate configured' rather than 'No evidence'. An "
          "all-blank gate is no gate, which is `gate_of`'s own rule",
          _ev_tasks["P1.3"]["gateSource"] == "phase"
          and _ev_tasks["P2.1"]["gateSource"] is None
          and _ev_phases["P2"]["gateSource"] is None
          and _ev_tasks["P2.1"]["testEvidence"] is None,
          repr((_ev_tasks["P1.3"]["gateSource"], _ev_tasks["P2.1"]["gateSource"])))
    # THE ONE VALUE EXPRESSED IN TWO PLACES, pinned rather than commented.
    # `_gate_source` mirrors `run-test-gate.gate_of`'s resolution because that
    # file is an entry point at layer 7 and this module sits at 4. A comment
    # claiming two implementations agree is not a check; this drives both.
    _gate_mod = _loader.load_script("run-test-gate.py", modname="audit_rtg_ev")
    _gate_pairs = []
    for _ph in _ev_manifest["phases"]:
        _gate_pairs.append((M._gate_source(_ph),
                            _gate_mod.gate_of(_ev_manifest, _ph["id"])[1]
                            if _gate_mod.gate_of(_ev_manifest, _ph["id"])[0]
                            else None))
        for _t in _ph["tasks"]:
            _cmds, _src, _err = _gate_mod.gate_of(_ev_manifest, _ph["id"], _t["id"])
            _gate_pairs.append((M._gate_source(_ph, _t),
                                _src if _cmds else None))
    check("ev4 `_gate_source` answers exactly what `run-test-gate.gate_of` "
          "answers, over every subject in one fixture - task gate, phase "
          "fallback, blank-string gate and no gate at all. Whole pair list "
          "rather than 'at least one agrees', so a mutation that also broke "
          "something else cannot pass for this: %r" % (_gate_pairs,),
          bool(_gate_pairs)
          and all(mine == theirs for mine, theirs in _gate_pairs)
          # ...and the fixture really does exercise all three answers, or the
          # agreement above would be an agreement about one case.
          and set(m for m, _t in _gate_pairs) == set([None, "phase", "task"]))
    check("ev5 a count is THREE-VALUED or it is not a count: [] is 'compared, "
          "and there was nothing', a list is the finding, and None is 'no "
          "comparison was made'. `len(x or [])` maps all three onto a number "
          "and calls the third one clean, which is the merge the gate runner "
          "refuses to make",
          M._count_or_unknown([]) == 0
          and M._count_or_unknown(["a", "b"]) == 2
          and M._count_or_unknown(None) is None
          # Neither None nor a list: no basis to call it clean, so it lands on
          # unknown rather than on zero.
          and M._count_or_unknown("scripts/x.py") is None)
    _ev_unknown = M._evidence_facts({
        "runId": "r-u", "scope": "task", "status": "passed", "ts": "t",
        "observations": {"ranTotal": None, "countsBasis": "no counter",
                         "treeMutated": None, "treeBasis": "git could not say",
                         "coverage": None, "coverageBasis": "nothing declared"}})
    _ev_clean = M._evidence_facts({
        "runId": "r-c", "scope": "task", "status": "passed", "ts": "t",
        "observations": {"ranTotal": 0, "countsBasis": "counted",
                         "treeMutated": [], "treeBasis": "before and after",
                         "coverage": [], "coverageBasis": "asked"}})
    _ev_cols = dict((n, i) for i, n in enumerate(M.EVIDENCE_FIELDS))
    check("ev6 UNKNOWN AND CLEAN ARE DIFFERENT ROWS, in all three fields at "
          "once. A run whose tree was never compared, whose overlap was never "
          "asked for and whose checks nothing counted must not ship the same "
          "numbers as a run that compared, asked, counted and found nothing: "
          "%r vs %r"
          % ([_ev_unknown[_ev_cols[k]] for k in
              ("ranTotal", "treeMutated", "coverage")],
             [_ev_clean[_ev_cols[k]] for k in
              ("ranTotal", "treeMutated", "coverage")]),
          _ev_unknown[_ev_cols["ranTotal"]] is None
          and _ev_clean[_ev_cols["ranTotal"]] == 0
          and _ev_unknown[_ev_cols["treeMutated"]] is None
          and _ev_clean[_ev_cols["treeMutated"]] == 0
          and _ev_unknown[_ev_cols["coverage"]] is None
          and _ev_clean[_ev_cols["coverage"]] == 0
          # ...and every basis travels whole, because "unknown" without the
          # sentence that produced it is the shape nobody can act on.
          and _ev_unknown[_ev_cols["treeBasis"]] == "git could not say"
          and _ev_unknown[_ev_cols["countsBasis"]] == "no counter")
    check("ev7 a row with NO observations block answers unknown to all three "
          "rather than zero - the block is where every observation is written, "
          "so its absence means nobody wrote one down, not that nothing was "
          "found",
          [M._evidence_facts({"runId": "r"})[_ev_cols[k]]
           for k in ("ranTotal", "treeMutated", "coverage")] == [None, None, None])
    # --- the ledger read, against a real evidence directory --------------------
    _evproj = tempfile.mkdtemp(prefix="panel-evidence-")
    try:
        _atomic_write_json(_paths._config_path(_evproj), {})
        _evdir = _evidence.evidence_dir(_evproj)
        os.makedirs(_evdir, exist_ok=True)

        def _evrow(run_id, ts, **over):
            row = {"v": 1, "runId": run_id, "ts": ts, "scope": "task",
                   "taskId": "P1.1", "phaseId": "P1", "status": "passed",
                   "durationMs": 1200, "attempt": 2,
                   "steps": [{"name": "unit", "exit": 0, "ran": 12,
                              "durationMs": 900, "command": "pytest -q"}],
                   "observations": {"ranTotal": 12, "countsBasis": "counted",
                                    "treeMutated": [], "treeBasis": "both ends",
                                    "coverage": ["src/a.py"],
                                    "coverageBasis": "declared"}}
            row.update(over)
            return row

        with open(os.path.join(_evdir, "2026-08.w1.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(_evrow("r-1", "2026-08-20T10:00:00Z")) + "\n")
            fh.write(json.dumps(_evrow("r-old", "2026-08-19T10:00:00Z")) + "\n")
            fh.write("{not json\n")
        _ev_out = M.evidence_view(_evproj, _ev_view)
        check("ev8 the payload ships the runs the plan POINTS AT and no others - "
              "keyed by runId, with the column names beside them so the browser "
              "reads its rows rather than trusting an order. `r-old` is a real "
              "row in the same file that nothing points at, which is what makes "
              "this a cut rather than a copy: %r" % (sorted(_ev_out["runs"]),),
              # `.get`, never `[...]`: a payload that LOST a key must fail
              # this case by name rather than raise and take every case below
              # it with it.
              sorted(_ev_out["runs"]) == ["r-1"]
              and _ev_out.get("fields") == list(M.EVIDENCE_FIELDS)
              and _ev_out.get("stepFields") == list(M.EVIDENCE_STEP_FIELDS))
        _ev_r1 = dict(zip(M.EVIDENCE_FIELDS, _ev_out["runs"]["r-1"]))
        check("ev9 ...and the row carries what a badge and its detail need: the "
              "verdict, when, the attempt, the duration, the three observations "
              "and one positional row per step read against stepFields",
              _ev_r1["status"] == "passed" and _ev_r1["at"] == "2026-08-20T10:00:00Z"
              and _ev_r1["attempt"] == 2 and _ev_r1["durationMs"] == 1200
              and _ev_r1["ranTotal"] == 12 and _ev_r1["treeMutated"] == 0
              and _ev_r1["coverage"] == 1
              and _ev_r1["steps"] == [["unit", 0, 12, 900, None]],
              repr(_ev_r1))
        check("ev10 NEITHER SPELLING OF A COMMAND CROSSES. A step's command is "
              "either the manifest's published string or a digest of an ad-hoc "
              "one, and a badge in a table renders neither - shipping it would "
              "put a command on a surface with no room to say which of the two "
              "it is",
              "command" not in M.EVIDENCE_STEP_FIELDS
              and "commandSha256" not in M.EVIDENCE_STEP_FIELDS
              and "pytest -q" not in json.dumps(_ev_out))
        check("ev11 a torn line is COUNTED and the files are counted, because a "
              "pointer whose run is missing has to say WHY - an evidence "
              "directory that was never written and one whose lines could not "
              "be parsed are different answers and the badge's basis needs both",
              _ev_out["files"] == 1 and _ev_out["unreadable"] == 1)
        # A SECOND ROW WEARING ONE runId, newest first by `ts`. Two worktrees
        # write two files whose concatenation is in no meaningful order, so
        # reading position would make "the run" depend on a directory listing.
        with open(os.path.join(_evdir, "2026-08.w2.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(_evrow("r-1", "2026-08-21T10:00:00Z",
                                       status="failed")) + "\n")
        _ev_dup = M.evidence_view(_evproj, _ev_view)
        check("ev12 two rows wearing one runId resolve to the NEWEST by ts, not "
              "to whichever file the directory listed first - the older row is "
              "in the earlier file, so a position read would have answered "
              "'passed'",
              dict(zip(M.EVIDENCE_FIELDS,
                       _ev_dup["runs"]["r-1"]))["status"] == "failed"
              and _ev_dup["files"] == 2)
        # A POINTER THE LEDGER CANNOT ANSWER, which is the third badge and not
        # the absent one. The counts are what let the page say why.
        _ev_missing = M.evidence_view(_evproj, M._composition_view({
            "phases": [{"id": "P9", "title": "x", "status": "pending",
                        "testGate": ["lint"],
                        "tasks": [{"id": "P9.1", "title": "y",
                                   "status": "done",
                                   "testEvidence": {"runId": "r-gone",
                                                    "status": "passed",
                                                    "at": "2026-08-01T00:00:00Z"}}]}]}))
        check("ev13 a pointer the ledger does not hold ships NO run - which is "
              "what lets the page say 'Pointer without evidence' rather than "
              "rendering the cached verdict as if it had been read. The counts "
              "come back non-zero, so the sentence has a basis and cannot be "
              "confused with an empty ledger",
              _ev_missing["runs"] == {} and _ev_missing["files"] == 2
              and _ev_missing["unreadable"] == 1)
        check("ev14 every exit ships ONE key set - the empty shape and a "
              "populated read cannot disagree, which is the `undefined` on a "
              "fresh install that only the reader least placed to report it "
              "ever meets",
              sorted(M.empty_evidence()) == sorted(_ev_out)
              and sorted(M.empty_evidence()) == sorted(_ev_missing))
        check("ev15 a project with no evidence directory at all is an ANSWER "
              "and never a raise: no runs, no files, nothing unreadable",
              M.evidence_view(os.path.join(_evproj, "nope"), _ev_view)
              == M.empty_evidence())
    finally:
        shutil.rmtree(_evproj, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_composition.py --selftest\n")
    raise SystemExit(2)
