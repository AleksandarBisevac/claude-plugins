#!/usr/bin/env python3
"""
The cases for `_priority.py` — which READY task the orchestrator reaches for first.

Pure arithmetic over dicts, so there is not a fixture directory anywhere below.

WHAT IS PINNED, and why each one is here rather than trusted:

- **A manifest with NO priority orders exactly as it did before.** `n1` looks
  vacuous — it passes by construction on the code that existed before this module
  — and it is the ONLY case that fails if `sort_key` ever becomes unconditional
  (say by treating an absent tier as 0, which would put every unpinned phase in
  FRONT). It is the second-direction case for a conditional fix, kept for exactly
  the reason `no-silent-pass` names.
- **Adding a priority to ONE phase does not re-sort the others.** `n2` is the
  same claim one step in: the pinned phase leads and the rest keep their written
  order, rather than the whole list being re-derived from something else.
- **`order()` returns a NEW list.** The display surfaces read the same list and
  must keep showing the plan as written; an in-place sort would silently reorder
  every reader.
- **Invalid values are unprioritised AND reported.** `tier_of` and
  `invalid_tiers` answer different questions, and a value that orders nothing
  while nobody mentions it is the silent-drop this module refuses.
- **The tie-break is named, deterministic and manifest order.** `u2` proves the
  winner is the FIRST holder rather than "whichever the sort happened to reach".
- **A pin that cannot be honoured produces a note naming the substitute.** And
  `p4` is its second-direction case: a pin whose waits are clear produces NO
  note, which is what fails if the note ever becomes unconditional.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _priority as M                              # noqa: E402
import _manifest_io as _mio                        # noqa: E402


def _ph(pid, tier=None, status="pending", blocked=None):
    """One phase, carrying `priority` only when a tier was asked for — an ABSENT
    key and `priority: None` are different documents, and the code tells them
    apart."""
    out = {"id": pid, "title": pid, "status": status, "tasks": []}
    if tier is not None:
        out[M.FIELD] = tier
    if blocked is not None:
        out["blockedBy"] = blocked
    return out


def _ids(phases):
    return [p["id"] for p in phases]


def _cases(check):
    # --- what a valid priority is ---------------------------------------------
    check("t1 a positive integer is a tier",
          M.tier_of(_ph("P1", 3)) == 3, repr(M.tier_of(_ph("P1", 3))))
    check("t2 an ABSENT priority is None - unprioritised, which is a class of "
          "its own and not tier 0",
          M.tier_of(_ph("P1")) is None, repr(M.tier_of(_ph("P1"))))
    for bad in (0, -3, "1", None, 1.5, [], {}):
        check("t3 %r is not a tier, so the phase sorts as unprioritised" % (bad,),
              M.tier_of({"id": "P1", M.FIELD: bad}) is None,
              repr(M.tier_of({"id": "P1", M.FIELD: bad})))
    check("t4 `priority: true` is NOT tier 1 - bool is an int in Python, and a "
          "boolean here is a typo rather than a rank",
          M.tier_of({"id": "P1", M.FIELD: True}) is None,
          repr(M.tier_of({"id": "P1", M.FIELD: True})))
    check("t5 a non-dict phase yields None rather than raising - these surfaces "
          "render manifests the validator has already faulted",
          M.tier_of("nope") is None and M.tier_of(None) is None)

    # --- the case that catches an over-eager sort ------------------------------
    plain = [_ph("P1"), _ph("P2"), _ph("P3")]
    check("n1 SECOND-DIRECTION CASE: a manifest with NO priority anywhere orders "
          "exactly as it is written. This reads vacuous and passes by "
          "construction on the code before this module existed - it is the "
          "PROPERTY every other case here is measured against, and what goes red "
          "the day the comparator starts ranking unpinned phases by anything "
          "(id, title, progress) instead of leaving them alone",
          _ids(M.order(plain)) == ["P1", "P2", "P3"], repr(_ids(M.order(plain))))
    one = [_ph("P1"), _ph("P2"), _ph("P3", 1), _ph("P4")]
    check("n2 adding a priority to ONE phase moves that phase and NOTHING else: "
          "the other three keep the order they were written in",
          _ids(M.order(one)) == ["P3", "P1", "P2", "P4"],
          repr(_ids(M.order(one))))
    # The mutation `n3` and `n4` exist for, computed rather than described: an
    # "absent priority is tier 0" comparator is the obvious wrong version, and it
    # leaves `n1` green (every key is (0, 0, index), so an unpinned plan still
    # orders as written) while putting every unpinned phase in FRONT of the pin.
    # A mutation a suite only talks about is a mutation nobody ran.
    def _naive_key(phase, index):
        return (0, M.tier_of(phase) or 0, index)

    _naive = [one[i] for i in sorted(range(len(one)),
                                     key=lambda i: _naive_key(one[i], i))]
    check("n2m mutation proof: the absent-is-tier-0 comparator this replaces "
          "puts the PINNED phase last and reads clean on an unpinned plan, which "
          "is exactly why n3 and n4 are the cases that catch it and n1 is not",
          _ids(_naive) == ["P1", "P2", "P4", "P3"]
          and [_ids([plain[i] for i in sorted(range(len(plain)),
                                              key=lambda i: _naive_key(plain[i], i))])]
          == [_ids(M.order(plain))],
          repr(_ids(_naive)))
    check("n3 every unprioritised phase sorts AFTER every prioritised one, "
          "however high the tier - absent is a separate class, not a middle",
          _ids(M.order([_ph("P1"), _ph("P2", 99)])) == ["P2", "P1"],
          repr(_ids(M.order([_ph("P1"), _ph("P2", 99)]))))
    shared = [_ph("P1", 2), _ph("P2", 1), _ph("P3", 2), _ph("P4")]
    check("n4 a shared tier keeps manifest order INSIDE the tier - 2, 3, 4 are "
          "shared on purpose, so ranking them against each other is the "
          "renumbering work this scheme avoids",
          _ids(M.order(shared)) == ["P2", "P1", "P3", "P4"],
          repr(_ids(M.order(shared))))
    src = [_ph("P1"), _ph("P2", 1)]
    before = list(src)
    M.order(src)
    check("n5 order() does not sort IN PLACE - the display surfaces read the same "
          "list and must keep showing the plan as it was written",
          src == before and src[0]["id"] == "P1", repr(_ids(src)))
    check("n6 an empty or absent phase list is an empty order, not a crash",
          M.order([]) == [] and M.order(None) == [])

    # --- the key itself -------------------------------------------------------
    check("k1 sort_key is a TUPLE, so a per-task tier is a member added later "
          "rather than a rewrite of the comparison",
          isinstance(M.sort_key(_ph("P1", 1), 0), tuple)
          and len(M.sort_key(_ph("P1", 1), 0)) == 3)
    check("k2 the unprioritised key differs from every prioritised key in its "
          "FIRST member - which is what makes 'after all of them' true without "
          "inventing a sentinel tier",
          M.sort_key(_ph("P1"), 0)[0] > M.sort_key(_ph("P2", 10 ** 6), 5)[0])
    check("k3 the index rides in the key, so two phases sharing a tier can never "
          "compare equal and the sort never has to fall back to the dicts",
          M.sort_key(_ph("P1", 2), 0) != M.sort_key(_ph("P2", 2), 1))

    # --- ranking the ready list ------------------------------------------------
    p_a, p_b = _ph("P1"), _ph("P2", 1)
    rows = [(p_a, 0, 0, "P1.1"), (p_a, 0, 1, "P1.2"), (p_b, 1, 2, "P2.1")]
    check("r1 rank_ready puts the pinned phase's task first and keeps document "
          "order INSIDE a phase - priority ranks phases, never the tasks in one",
          M.rank_ready(rows) == ["P2.1", "P1.1", "P1.2"],
          repr(M.rank_ready(rows)))
    flat = [(_ph("P1"), 0, 0, "P1.1"), (_ph("P2"), 1, 1, "P2.1")]
    check("r2 SECOND-DIRECTION CASE: with no priority the rows come back in the "
          "order they were walked - the ready list of an unpinned plan is "
          "byte-identical to the one the pre-priority loop emitted",
          M.rank_ready(flat) == ["P1.1", "P2.1"], repr(M.rank_ready(flat)))
    check("r3 rank_ready never invents or drops a row - the SET is readiness's "
          "answer and this only re-orders it",
          sorted(M.rank_ready(rows)) == sorted(r[3] for r in rows))

    # --- uniqueness ------------------------------------------------------------
    check("u1 tier 1 has a holder when one phase takes it",
          M.tier_one_holder([_ph("P1"), _ph("P2", 1)]) == "P2")
    two = [_ph("P1", 1), _ph("P2", 1)]
    check("u2 with TWO holders the answer is the FIRST in manifest order - the "
          "tie-break is deterministic and named, not 'whichever the sort reached'",
          M.tier_one_holder(two) == "P1", repr(M.tier_one_holder(two)))
    check("u2b ...and reversing the manifest reverses the answer, so u2 is "
          "reading document order rather than the id",
          M.tier_one_holder(list(reversed(two))) == "P2")
    check("u3 no holder is None, not a phase and not an empty string",
          M.tier_one_holder([_ph("P1"), _ph("P2", 2)]) is None)
    check("u4 tier_conflicts names both holders when tier 1 is doubled",
          M.tier_conflicts(two) == [(1, ["P1", "P2"])], repr(M.tier_conflicts(two)))
    check("u5 SECOND-DIRECTION CASE: a SHARED tier is not a conflict - if this "
          "went red the validator would be reporting the normal case, which is "
          "how a rule gets switched off",
          M.tier_conflicts([_ph("P1", 2), _ph("P2", 2), _ph("P3", 2)]) == [],
          repr(M.tier_conflicts([_ph("P1", 2), _ph("P2", 2)])))
    check("u6 one holder of tier 1 is not a conflict either",
          M.tier_conflicts([_ph("P1", 1), _ph("P2", 2)]) == [])

    # --- maxTier is advisory ---------------------------------------------------
    over = [_ph("P1", 3), _ph("P2", 12), _ph("P3")]
    check("m1 over_max names the phase and the tier it was given - a note about "
          "a value nothing clamps has to carry the value that made it true",
          M.over_max(over, 9) == [("P2", 12)], repr(M.over_max(over, 9)))
    check("m2 NOTHING IS CLAMPED: the over-max phase still sorts by ordinary "
          "arithmetic, after every tier at or under the maximum",
          _ids(M.order(over)) == ["P1", "P2", "P3"], repr(_ids(M.order(over))))
    check("m3 a tier exactly AT the maximum is not over it",
          M.over_max([_ph("P1", 9)], 9) == [])
    check("m4 a max_tier that is not a positive integer reports nothing rather "
          "than reporting everything - a broken setting must not turn into a "
          "wall of notes about phases that are fine",
          M.over_max(over, "9") == [] and M.over_max(over, True) == [])

    # --- invalid values are reported, not absorbed -----------------------------
    junk = [_ph("P1"), {"id": "P2", M.FIELD: "1"}, {"id": "P3", M.FIELD: 0}]
    check("i1 invalid_tiers names each phase and the value it carries",
          M.invalid_tiers(junk) == [("P2", "1"), ("P3", 0)],
          repr(M.invalid_tiers(junk)))
    check("i2 SECOND-DIRECTION CASE: a phase with NO priority key is not "
          "reported - this is what fails if the check widens to 'any phase "
          "without a tier', which is nearly every phase in every plan",
          M.invalid_tiers([_ph("P1"), _ph("P2", 1)]) == [],
          repr(M.invalid_tiers([_ph("P1"), _ph("P2", 1)])))
    check("i3 the two answers are DIFFERENT questions: the same phase sorts as "
          "unprioritised AND is named as junk, which is what stops a value with "
          "no effect from being silently absorbed",
          M.tier_of(junk[1]) is None and M.invalid_tiers(junk)[0][0] == "P2")

    # --- the pin that cannot be honoured ---------------------------------------
    pinned = [_ph("P1"), _ph("P2"), _ph("P5", 1, blocked=["P2"])]
    pin = M.pinned_but_blocked(pinned, {"P5": ["P2"]}, finished=_mio.TERMINAL)
    check("p1 a pinned phase waiting on unfinished work is reported, with the "
          "tier and what it waits on",
          pin == {"phaseId": "P5", "tier": 1, "waitingOn": ["P2"]}, repr(pin))
    check("p2 the note names the task running INSTEAD - 'the pin was skipped' "
          "without the substitute reads as 'the run stalled'",
          M.note(pin, "P1.1")
          == "P5 holds priority 1 but is waiting on P2 (not done) - running "
             "P1.1 instead",
          repr(M.note(pin, "P1.1")))
    check("p3 ...and with nothing ready at all it says THAT, rather than "
          "printing a blank where a task id belongs",
          "nothing else is ready either" in M.note(pin, None),
          repr(M.note(pin, None)))
    clear = [_ph("P1"), _ph("P5", 1)]
    check("p4 SECOND-DIRECTION CASE: a pin whose waits are clear produces NO "
          "note, and note(None, ...) is None. This is the case that goes red if "
          "the note ever becomes unconditional - every run would then carry a "
          "sentence about a pin that was honoured",
          M.pinned_but_blocked(clear, {}, finished=_mio.TERMINAL) is None
          and M.note(None, "P1.1") is None)
    done = [_ph("P5", 1, status="done", blocked=["P2"]), _ph("P1")]
    check("p5 a DONE pinned phase is a pin that was honoured, not one that was "
          "skipped - it is passed over rather than reported",
          M.pinned_but_blocked(done, {"P5": ["P2"]},
                               finished=_mio.TERMINAL) is None)
    check("p5b ...and 'cancelled' counts as finished for the same reason, which "
          "is why the statuses arrive as an argument from the module that owns "
          "what TERMINAL means",
          M.pinned_but_blocked([_ph("P5", 1, status="cancelled", blocked=["P2"])],
                               {"P5": ["P2"]}, finished=_mio.TERMINAL) is None)
    check("p6 an UNPRIORITISED phase that is blocked is not a pin and is never "
          "reported - order() puts every pinned phase first, so the walk stops "
          "at the first phase with no tier",
          M.pinned_but_blocked([_ph("P1", blocked=["P2"])], {"P1": ["P2"]},
                               finished=_mio.TERMINAL) is None)
    layered = [_ph("P1", 2, blocked=["P9"]), _ph("P2", 1)]
    check("p7 the TOP pin decides: with tier 1 free to run there is nothing to "
          "report, even though a lower tier is blocked - the note is about the "
          "phase that was skipped in favour of another, not about every wait",
          M.pinned_but_blocked(layered, {"P1": ["P9"]},
                               finished=_mio.TERMINAL) is None)
    check("p8 an empty unmet map is treated as 'nothing waiting', and a missing "
          "one does not raise",
          M.pinned_but_blocked(pinned, None, finished=_mio.TERMINAL) is None)

    # --- the agreement with the layout owner -----------------------------------
    check("x1 `priority` is what _manifest_io calls an INDEX-ONLY field. The two "
          "modules are layer-mates and cannot import each other, so the "
          "agreement is pinned rather than assumed - a rename in one would "
          "otherwise leave the other writing into a shard body",
          M.FIELD in _mio.INDEX_ONLY_FIELDS, repr(_mio.INDEX_ONLY_FIELDS))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__priority.py --selftest\n")
    raise SystemExit(2)
