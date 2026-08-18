#!/usr/bin/env python3
"""
The cases for `_manifest_ado.py` — `meta.ado`, checked without a network.

`check_ado_meta` is the ONE front door: `validate()` calls it for the manifest
and the panel's `write_ado` (PUT /api/ado) calls it for a candidate save, so the
CLI and the panel cannot disagree about what a valid connector config is. That
shared-ness is pinned here by identity rather than described in a comment — a
second implementation on the panel side is the failure this module exists to
make impossible.

The line every case is drawn against: a wrong TYPE is a finding (a config that
would be misread), an unknown KEY is a did-you-mean warning (the typo catcher).
`statemap` configuring nothing is exactly the silence worth naming, and it is
worth a case precisely because nothing else in the pipeline notices.

`null`/absent means the connector is off, and that is an ANSWER — the suite
pins the silence, because a validator that warned about an unconfigured
optional feature would nag every project that never wanted it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_ado as M                          # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _manifest_rules as _rules                   # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    def ado(block, label, want_finding=None, want_warning=None):
        f, w = M.check_ado_meta(block)
        if want_finding is None and want_warning is None:
            check(label, f == [] and w == [], "f=%r w=%r" % (f, w))
            return
        ok = True
        if want_finding is not None:
            ok = ok and any(want_finding in x for x in f)
        if want_warning is not None:
            ok = ok and any(want_warning in x for x in w)
        check(label, ok, "f=%r w=%r" % (f, w))

    ado(None, "ma1 a null connector block is silent - absent means off, and "
              "off is an answer rather than a defect")
    ado({}, "ma2 ...and an empty object is silent too: every key below is "
            "optional, so an empty block configures nothing and breaks nothing")
    ado("nope", "ma3 a non-object block is a finding naming the type it got",
        want_finding="ado must be an object or null")

    ado({"organization": ""}, "ma4 an empty organization is a finding - it "
        "reads as configured while naming no org",
        want_finding="meta.ado.organization")
    ado({"enabled": "yes"}, "ma5 a string where a boolean belongs is a "
        "finding: `\"false\"` is truthy and would silently enable the "
        "connector", want_finding="must be true or false")
    ado({"tag": ""}, "ma6 an empty provenance tag is a finding, while null is "
        "legal - the two say different things and only one is typeable by "
        "accident", want_finding="meta.ado.tag")
    ado({"tag": None}, "ma7 ...and null IS legal: it means 'no provenance "
                       "tag', which is the case ma6 must not have outlawed")

    ado({"statemap": {}}, "ma8 `statemap` draws a did-you-mean rather than a "
        "finding - a mis-cased key configures nothing at all, which is the "
        "silence worth naming", want_warning="did you mean 'stateMap'")
    ado({"stateMap": {"tsak": {}}}, "ma9 ...and an unknown block inside "
        "stateMap is named too, so a typo'd kind cannot silently never fire",
        want_warning="meta.ado.stateMap: unknown key 'tsak'")
    ado({"stateMap": {"task": {"in_progres": "Active"}}},
        "ma10 ...and so is a typo'd STATUS key inside a kind: the map would "
        "load, and the one transition it was written for would never move",
        want_warning="meta.ado.stateMap.task: unknown key 'in_progres'")
    ado({"stateMap": {"task": {"done": None}}},
        "ma11 ...while an explicit null on a known status is legal and "
        "silent: null means 'never move this transition'")
    ado({"stateMap": {"phase": {"done": "Done"}}},
        "ma12 `phase` is a THIRD kind with its own vocabulary - a Scrum PBI "
        "knows no 'In Progress', so a phase block keyed by phase statuses "
        "must not be reported as unknown")

    ado({"sprint": {"mode": "current"}}, "ma13 a sprint block with no team is "
        "a finding: 'current' is defined by a team's iteration calendar, and "
        "without one there is nothing to resolve",
        want_finding="requires a non-empty 'team'")
    ado({"sprint": {"team": "T", "mode": "static"}},
        "ma14 ...and any mode but 'current' is a finding that points at "
        "iterationPath, which is where a static path belongs",
        want_finding="meta.ado.sprint.mode")
    ado({"pull": {"tags": "audit"}}, "ma15 pull.tags must be an ARRAY - a "
        "bare string would be iterated per-character into five one-letter tags",
        want_finding="meta.ado.pull.tags: must be an array")
    ado({"onComplete": {"remainingWork": -1}},
        "ma16 a negative remainingWork is a finding; the field is a number of "
        "hours and there is no such thing as less than none",
        want_finding="meta.ado.onComplete.remainingWork")
    ado({"onComplete": {"remainingWork": True}},
        "ma17 ...and a boolean is a finding too, which is the case that fails "
        "if the `isinstance(rw, bool)` exclusion is dropped and `true` starts "
        "passing as the number 1",
        want_finding="meta.ado.onComplete.remainingWork")

    ado({"identityMap": {"a@x.example": "A@ado.example",
                         "b@x.example": "a@ado.example"}},
        "ma18 two ledger identities mapping to ONE ADO account is a WARNING, "
        "not a finding - usually a paste error, but one person can hold two "
        "ledger identities. Compared case-insensitively, because ADO is",
        want_warning="is the target of 2 ledger identities")
    ado({"identityMap": {"a@x.example": 7}},
        "ma19 ...while a non-string VALUE is a finding: the map is advisory "
        "in use and structural in shape",
        want_finding="must be a non-empty ADO identity string")
    ado({"identityMap": {"a@x.example": "a@ado.example"}},
        "ma20 ...and a well-formed one-to-one map is silent, which is the "
        "case that fails if the duplicate warning becomes unconditional")

    # --- the front door, and the aliases ---
    check("ma21 `check_ado_meta` reached through `_manifest_rules` IS this "
          "function - one front door, pinned by identity rather than by a "
          "comment saying so",
          _rules.check_ado_meta is M.check_ado_meta)
    check("ma22 `_check_identity_map` is folded INTO the front door rather "
          "than called separately: a duplicate target surfaces from "
          "check_ado_meta alone, which is what makes one call enough",
          _rules._check_identity_map is M._check_identity_map)
    _forked = [n for n in ("STATUS", "BUG_STATUS", "KNOWN_ADO", "_unknown_keys")
               if getattr(M, n) is not getattr(_vocab, n)]
    check("ma23 the vocabulary this module reads is `_manifest_vocab`'s "
          "objects, not its own copies: %r" % (_forked,), _forked == [])
    # The stateMap vocabulary is BUILT from those tuples, so a fork would show
    # up as a status this module accepts and the walk rejects. Asserted through
    # behaviour rather than through the tuple, so the wiring is what is pinned.
    _f, _w = M.check_ado_meta({"stateMap": {"bug": {"wontfix": "Removed"}}})
    check("ma24 ...and it is those tuples the stateMap keys are checked "
          "against: a bug status legal in BUG_STATUS is legal here",
          _f == [] and _w == [], "f=%r w=%r" % (_f, _w))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_ado.py --selftest\n")
    raise SystemExit(2)
