#!/usr/bin/env python3
"""
The cases for `_ado_drift.py` — who wrote a linked work item last.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The pair that differs in ONE field.** `ad3` builds two fixtures whose only
  difference is `System.ChangedDate` and asserts BOTH verdicts in one case. A file
  that only ever asserted `external_change` would pass on a version that returned
  it unconditionally; the pair is what makes the comparison load-bearing.
- **The tolerance, in both directions.** `ad5` is our own write with a few seconds
  of clock skew and must read `local_ahead`; `ad6` is an hour later and must read
  `external_change`. Delete `DEFAULT_TOLERANCE_S` (or make it 0) and `ad5` goes red
  — which is the whole point of measuring skew instead of describing it.
- **`unknown` is a verdict, not a gap.** Three ways to arrive there (no
  `lastSyncedAt`, no `ChangedDate`, an unparseable stamp) and — `ad11` — the rule
  that `advice()` returns NOTHING for it. A suggestion built on a missing timestamp
  is the defect this module exists to remove, wearing a helpful voice.
- **Two silences that must not read alike.** `System.ChangedBy` absent and
  `System.ChangedBy` present-but-empty both yield no name; `ad15` pins that their
  BASIS differs, because "ADO did not send it" and "we read a shape we did not
  expect" send a reader to different places.
- **The measured shape.** `ad1` uses the stamp probed live off the lab board
  (`'2026-08-21T06:30:20.377Z'`, fractional seconds + `Z`) and the identity OBJECT
  `az` really returns. A fixture invented from the docstring would encode my
  assumption instead of ADO's behaviour.
- **Nothing is dropped to make a table look complete.** `ad19`/`ad20` pin that a
  fetched item no link claims, and a link whose item was not fetched, both come
  back named.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_drift as M                             # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402


# The identity object `az boards work-item show` really returns, trimmed to the
# keys this module reads. Probed, not invented.
WHO = {"displayName": "Ana Kovac", "uniqueName": "ana@example.com",
       "id": "2d168b7b-5ecd-66f8-afab-5b17e6729517"}

SYNCED = "2026-08-21T18:02:00Z"


def _fields(changed_at, state="Active", who=WHO):
    """One fetched item's fields. Callers vary ONE thing at a time."""
    out = {"System.State": state, "System.ChangedDate": changed_at}
    if who is not None:
        out["System.ChangedBy"] = who
    return out


def _link(synced=SYNCED, ado_id=5120, origin=None):
    out = {"id": ado_id, "url": "https://dev.azure.com/x/_workitems/edit/5120",
           "lastSyncedAt": synced}
    if origin is not None:
        out["origin"] = origin
    return out


MANIFEST = {
    "phases": [
        {"id": "P1", "title": "one", "ado": {"id": 4001, "lastSyncedAt": SYNCED,
                                             "origin": "created"},
         "tasks": [
             {"id": "T1.1", "ado": {"id": 5120, "lastSyncedAt": SYNCED,
                                    "origin": "created"}},
             {"id": "T1.2", "ado": None},
             {"id": "T1.3", "ado": {"id": True, "lastSyncedAt": SYNCED}},
         ]},
        {"id": "P2", "title": "two", "tasks": []},
    ],
    "bugs": [
        {"id": "BUG-7", "ado": {"id": 4890, "lastSyncedAt": SYNCED,
                                "origin": "imported"}},
        {"id": "BUG-8", "ado": {"id": 4891, "lastSyncedAt": SYNCED}},
    ],
}


def _cases(check):
    # --- the time question, on the measured shape ---------------------------------
    _probed = "2026-08-21T06:30:20.377Z"
    _row = M.classify(_link(synced="2026-08-21T06:00:00Z"), _fields(_probed),
                      mapped="Closed")
    check("ad1 the stamp `az` really sends - fractional seconds and a trailing Z - "
          "parses and classifies, because `_usage_core.parse_ts` is reused rather "
          "than a fourth ISO parser written: %r" % (_row["class"],),
          _row["class"] == M.EXTERNAL_CHANGE and _row["changedAt"] == _probed)
    check("ad2 ...and the identity OBJECT is read for a name, not stringified: %r"
          % (_row["changedBy"],),
          _row["changedBy"] == "Ana Kovac"
          and _row["changedByBasis"] == "System.ChangedBy.displayName")

    _after = M.classify(_link(), _fields("2026-08-21T19:40:00Z"), mapped="Active")
    _before = M.classify(_link(), _fields("2026-08-21T17:20:00Z"), mapped="Active")
    check("ad3 THE PAIR: two fixtures differing ONLY in System.ChangedDate give "
          "the two opposite verdicts - 19:40 (after our 18:02 sync) is external, "
          "17:20 is our own side being ahead. Asserting one alone would pass on a "
          "version that answered it unconditionally: %r vs %r"
          % (_after["class"], _before["class"]),
          _after["class"] == M.EXTERNAL_CHANGE
          and _before["class"] == M.LOCAL_AHEAD)
    check("ad4 ...and each carries the basis that makes it true - both stamps and "
          "the tolerance appear in it, so a reader can redo the comparison: %r"
          % (_after["basis"],),
          "2026-08-21T19:40:00Z" in _after["basis"]
          and SYNCED in _after["basis"] and "tolerance" in _after["basis"])

    # The tolerance, both ways. This is the pair that goes red if the margin is
    # deleted: our own write lands a few seconds after the stamp we recorded.
    _skew = M.classify(_link(), _fields("2026-08-21T18:02:03Z"), mapped="Active")
    _hour = M.classify(_link(), _fields("2026-08-21T19:02:00Z"), mapped="Active")
    check("ad5 THE TOLERANCE: a change 3s after lastSyncedAt is OUR OWN write seen "
          "through clock skew (local `date -u` vs ADO's server clock), so it must "
          "NOT be reported as somebody else's: %r" % (_skew["class"],),
          _skew["class"] == M.LOCAL_AHEAD)
    check("ad6 ...and an hour later is not skew: %r" % (_hour["class"],),
          _hour["class"] == M.EXTERNAL_CHANGE)
    check("ad7 ...and the margin is a knob, so a caller on a badly skewed machine "
          "can widen it rather than get a confident wrong answer",
          M.classify(_link(), _fields("2026-08-21T18:30:00Z"), mapped="Active",
                     tolerance=3600)["class"] == M.LOCAL_AHEAD
          and M.DEFAULT_TOLERANCE_S > 0)

    # --- unknown is an answer ------------------------------------------------------
    _never = M.classify({"id": 1}, _fields("2026-08-21T19:40:00Z"), mapped="Active")
    _nostamp = M.classify(_link(), {"System.State": "Active"}, mapped="Active")
    _junk = M.classify(_link(synced="last tuesday"),
                       _fields("2026-08-21T19:40:00Z"), mapped="Active")
    check("ad8 a link that was never synced has NO basis for either verdict: %r"
          % (_never["class"],),
          _never["class"] == M.UNKNOWN and "lastSyncedAt absent" in _never["basis"])
    check("ad9 an item ADO sent without a change stamp, likewise - and the basis "
          "names the FIELD, not the link, because they send you to different "
          "places: %r" % (_nostamp["basis"],),
          _nostamp["class"] == M.UNKNOWN
          and _nostamp["basis"].startswith("System.ChangedDate absent"))
    check("ad10 an unparseable stamp is unknown too, and the basis QUOTES the "
          "value - a reader who cannot see it cannot fix it: %r" % (_junk["basis"],),
          _junk["class"] == M.UNKNOWN and "last tuesday" in _junk["basis"])
    check("ad11 THE HOUSE RULE: `unknown` draws NO suggested action. A suggestion "
          "built on a missing timestamp is the same defect in a helpful voice",
          M.advice(_never) is None and M.advice(_nostamp) is None
          and M.advice(_junk) is None)
    # Drifting versions of the same pair: the states DISAGREE here, which is what
    # gives a row an action at all. The in-sync pair above deliberately has none.
    _d_after = M.classify(_link(), _fields("2026-08-21T19:40:00Z", state="Closed"),
                          mapped="Active")
    _d_before = M.classify(_link(), _fields("2026-08-21T17:20:00Z", state="Closed"),
                           mapped="Active")
    check("ad12 ...while the two DRIFTING verdicts each draw their own action, and "
          "they are different actions - the whole finding is that these two were "
          "one: %r / %r" % (M.advice(_d_before), M.advice(_d_after)),
          M.advice(_d_before) == "push"
          and M.advice(_d_after) != "push"
          and "overwrites" in (M.advice(_d_after) or ""))
    check("ad12b ...and a row with no drift draws no action even when its stamps "
          "are perfectly readable, so 'nothing to do' is not spelled the same way "
          "as 'no basis to say': %r / %r" % (M.advice(_after), M.advice(_before)),
          M.advice(_after) is None and M.advice(_before) is None
          and _after["drift"] is False and _before["drift"] is False)

    # --- the state question is separate, and may be absent -------------------------
    _uncompared = M.classify(_link(), _fields("2026-08-21T19:40:00Z"))
    check("ad13 with no mapped state supplied, `drift` is None and the verdict "
          "SAYS the comparison was not made - never that the item is in sync. "
          "sync.md owns the stateMap table; a copy here would be a second answer: "
          "%r" % (M.verdict(_uncompared),),
          _uncompared["drift"] is None
          and M.verdict(_uncompared) == "state not compared (no mapped state "
                                        "supplied)"
          and M.advice(_uncompared) is None)
    _agree = M.classify(_link(), _fields("2026-08-21T19:40:00Z", state="Closed"),
                        mapped="Closed")
    check("ad14 an item somebody ELSE moved into the state we wanted is in sync "
          "AND externally written - collapsing the two questions into one enum "
          "would hide the second half: %r" % (M.verdict(_agree),),
          _agree["drift"] is False and _agree["class"] == M.EXTERNAL_CHANGE
          and "not by us" in M.verdict(_agree)
          and "overwrite" not in M.verdict(_agree))

    # --- the two silences of System.ChangedBy --------------------------------------
    _absent = M.changed_by({"System.State": "Active"})
    _empty = M.changed_by({"System.ChangedBy": {"id": "x"}})
    check("ad15 TWO SILENCES, TWO BASES: `ChangedBy` absent and `ChangedBy` "
          "present-but-nameless both yield no name, and a reader has to be able "
          "to tell 'ADO did not send it' from 'we read a shape we did not "
          "expect': %r vs %r" % (_absent["basis"], _empty["basis"]),
          _absent["name"] is None and _empty["name"] is None
          and _absent["basis"] != _empty["basis"]
          and "absent" in _absent["basis"]
          and "neither displayName nor uniqueName" in _empty["basis"])
    check("ad16 uniqueName is the fallback when displayName is missing, and the "
          "basis says which one was read",
          M.changed_by({"System.ChangedBy": {"uniqueName": "a@b.c"}})
          == {"name": "a@b.c", "basis": "System.ChangedBy.uniqueName"})
    _str = M.changed_by({"System.ChangedBy": "Ana Kovac"})
    check("ad17 a PLAIN STRING is accepted, because the MCP transport could not be "
          "probed from here (its server authenticates as a different identity and "
          "is not authorized on the lab board) - and the basis says exactly that, "
          "so the untested shape is visible rather than assumed: %r"
          % (_str["basis"],),
          _str["name"] == "Ana Kovac" and "not probed" in _str["basis"])

    # --- origin --------------------------------------------------------------------
    check("ad18 origin: written by a CREATE, written by a pull import, absent on a "
          "link that predates the field, and a typo - and the typo does NOT read "
          "like the absence, because one is history and the other is a mistake "
          "somebody has to fix",
          M.origin_of(_link(origin="created"))["origin"] == M.ORIGIN_CREATED
          and M.origin_of(_link(origin="imported"))["origin"] == M.ORIGIN_IMPORTED
          and M.origin_of(_link())["origin"] == M.UNKNOWN
          and "absent" in M.origin_of(_link())["basis"]
          and M.origin_of(_link(origin="Created"))["origin"] == M.UNKNOWN
          and "is not one of" in M.origin_of(_link(origin="Created"))["basis"])

    check("ad18b the vocabulary is the SAME OBJECT `_manifest_vocab` holds, not a "
          "copy of it - the validator that refuses a misspelled origin reads it "
          "from there, and two tuples would disagree eventually with the manifest "
          "as the only witness",
          M.ORIGINS is _vocab.ADO_ORIGIN
          and M.ORIGIN_CREATED == _vocab.ADO_ORIGIN_CREATED
          and M.ORIGIN_IMPORTED == _vocab.ADO_ORIGIN_IMPORTED)

    # --- the manifest walk ---------------------------------------------------------
    _inv = M.link_inventory(MANIFEST)
    _ids = [r["adoId"] for r in _inv]
    check("ad19 the inventory carries every INTEGER-linked item, phases first, and "
          "skips a null link, a phase with no tasks, and `id: true` - which would "
          "otherwise pass for a work-item id because bool subclasses int (the F15 "
          "shape the validator already refuses): %r" % (_ids,),
          _ids == [4001, 5120, 4890, 4891]
          and [r["kind"] for r in _inv] == ["phase", "task", "bug", "bug"])
    check("ad20 the breakdown counts what is NOT recorded too - `unknown` is how "
          "many links predate the field, and a reader who cannot see it reads the "
          "other two as the whole: %r" % (M.origin_breakdown(_inv),),
          M.origin_breakdown(_inv) == {"created": 2, "imported": 1, "unknown": 1,
                                       "total": 4})
    check("ad21 an empty manifest is an empty inventory and a zeroed breakdown, "
          "not an error - and `total` still agrees with the list",
          M.link_inventory({}) == [] and M.link_inventory(None) == []
          and M.origin_breakdown([])["total"] == 0)

    # --- join: nothing is dropped to make the table look complete ------------------
    _res = M.join(MANIFEST, [
        {"id": 5120, "fields": _fields("2026-08-21T19:40:00Z", state="Closed"),
         "mapped": "Active"},
        {"id": 4890, "fields": _fields("2026-08-21T17:00:00Z", state="Resolved"),
         "mapped": "Resolved"},
        {"id": 99999, "fields": _fields("2026-08-21T19:40:00Z")},
    ])
    check("ad22 a fetched item NO manifest link claims comes back named, rather "
          "than being dropped into a shorter table that looks complete: %r"
          % (_res["unlinked"],),
          [u["adoId"] for u in _res["unlinked"]] == [99999])
    check("ad23 ...and a LINKED item that was not fetched comes back too, because "
          "'we did not look at it' and 'it is fine' are different answers: %r"
          % ([u["adoId"] for u in _res["unfetched"]],),
          sorted(u["adoId"] for u in _res["unfetched"]) == [4001, 4891])
    _by_id = dict((r["adoId"], r) for r in _res["rows"])
    check("ad24 each row names the manifest item it belongs to, so the table can "
          "be read without a second lookup: %r"
          % ([(r["kind"], r["id"], r["adoId"]) for r in _res["rows"]],),
          _by_id[5120]["kind"] == "task" and _by_id[5120]["id"] == "T1.1"
          and _by_id[4890]["kind"] == "bug" and _by_id[4890]["id"] == "BUG-7")
    check("ad25 ...and carries the origin of the card it is about, which is what "
          "lets a push plan say it is writing to a card it did not create: %r"
          % (_by_id[4890]["origin"],),
          _by_id[4890]["origin"]["origin"] == M.ORIGIN_IMPORTED
          and _by_id[5120]["origin"]["origin"] == M.ORIGIN_CREATED)
    check("ad26 the summary counts the classes a caller prints, and the external "
          "count is the one the confirm gate needs: %r" % (M.summarize(_res),),
          M.summarize(_res) == {"total": 2, "external": 1, "localAhead": 0,
                               "unknown": 0, "inSync": 1, "uncompared": 0,
                               "unlinked": 1, "unfetched": 2})
    check("ad27 a fetched item with a non-integer id is reported, not silently "
          "skipped - the same bool trap as ad19, from the other side",
          [u["adoId"] for u in M.join(MANIFEST, [{"id": True, "fields": {}}])
           ["unlinked"]] == [True])
    check("ad28 the tolerance in force travels with the result, so a table that "
          "called a change external can be re-judged without guessing the margin",
          M.join(MANIFEST, [], tolerance=7)["tolerance"] == 7)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_drift.py --selftest\n")
    raise SystemExit(2)
