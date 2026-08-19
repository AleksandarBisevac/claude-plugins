#!/usr/bin/env python3
"""
The cases for `_manifest_vocab.py` — the manifest's words, and the four shape
checks every level of it shares.

Two kinds of case, and the second is the reason a table of literals earns a test
file at all.

THE RULES. `_unknown_keys`, `_require_fields`, `_safe_list`, `_strip_line_suffix`
and `_check_ado` are asked of a phase, a task and a bug alike, and each has one
behaviour that is easy to lose in a move: the did-you-mean hint fires only on a
case-insensitive collision, `_safe_list` refuses to iterate a bare string
per-character, and `_check_ado` is silent on an absent key and on an explicit null.

THE AGREEMENT. Four modules at layer 2 read this vocabulary and
`_manifest_rules` re-exports every name in it. Nothing compares those spellings
at runtime, so the risk this file guards is not that a tuple is wrong — it is
that a second copy appears. Every re-export is pinned with `is`, which fails on
a pasted-back literal and passes on an alias.

`TERMINAL` is asserted ABSENT here, and that is a layer case rather than a
naming one: it belongs to `_manifest_io`, so defining it in this module would
give this module an import, put it at layer 2, and push `_manifest_rules` past
the layer its own consumers leave free.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_vocab as M                        # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _manifest_rules as _rules                   # noqa: E402
import _manifest_ado as _ado                       # noqa: E402
import _manifest_typos as _typos                   # noqa: E402
import _manifest_crossrefs as _cross               # noqa: E402
import _manifest_phases as _phases                 # noqa: E402
import _help                                       # noqa: E402  (owns the schema walk these sets are checked against)


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the shared shape checks ---
    w = []
    M._unknown_keys({"reviewskill": 1}, {"reviewSkill"}, "meta", w)
    check("mv1 an unknown key that differs only in CASE draws a did-you-mean "
          "naming the intended key - the hint is a case-fold lookup, not an "
          "edit distance, so it never guesses",
          len(w) == 1 and "did you mean 'reviewSkill'" in w[0], w)
    w = []
    M._unknown_keys({"zzz": 1}, {"reviewSkill"}, "meta", w)
    check("mv2 ...and one with no near neighbour still gets named, rather "
          "than passing in silence",
          len(w) == 1 and "did you mean" not in w[0] and "'zzz'" in w[0], w)
    # The three prefixes are an escape hatch a hand-edited manifest relies on.
    w = []
    M._unknown_keys({"_note": 1, "$schema": 2, "//c": 3}, {"a"}, "meta", w)
    check("mv3 `_`, `$` and `//` prefixes are reserved and draw nothing - the "
          "case that fails if the escape hatch is narrowed to one of them",
          w == [], w)
    # The mutation this catches is `_unknown_keys` becoming unconditional: it
    # reads vacuous, and it is the only case that fails when the filter is
    # dropped and every key is reported.
    w = []
    M._unknown_keys({"reviewSkill": 1}, {"reviewSkill"}, "meta", w)
    check("mv4 ...and a KNOWN key draws nothing at all", w == [], w)

    check("mv5 `_safe_list` refuses a bare string rather than iterating it "
          "per-character, which is how a `blockedBy: \"P1\"` became two "
          "unresolvable one-letter references",
          M._safe_list("P1") == [] and M._safe_list(["P1"]) == ["P1"], "")
    check("mv6 `_strip_line_suffix` drops a line range and normalises "
          "backslashes, so a fileIndex key and a task's `files` entry compare",
          M._strip_line_suffix("a\\b.tsx:291-294,308") == "a/b.tsx",
          M._strip_line_suffix("a\\b.tsx:291-294,308"))

    f = []
    ok = M._require_fields({"id": "P1", "title": "", "status": "pending"},
                           "phase P1", f)
    check("mv7 `_require_fields` reports each missing/empty field by name and "
          "answers False - an empty title is missing, not present",
          ok is False and len(f) == 1 and "'title'" in f[0], f)

    f = []
    M._check_ado({}, "task T", f)
    check("mv8 `_check_ado` is silent when there is no `ado` key at all",
          f == [], f)
    f = []
    M._check_ado({"ado": None}, "task T", f)
    check("mv9 ...and silent on an explicit null, which is how /audit:sync "
          "spells 'unlinked'", f == [], f)
    f = []
    M._check_ado({"ado": {"id": "41"}}, "task T", f)
    check("mv10 ...but a STRING id is a finding: /audit:sync writes an int, "
          "and a quoted id compares unequal to every link the connector wrote",
          len(f) == 1 and "ado.id" in f[0], f)
    f = []
    M._check_ado({"ado": {"id": 41}}, "task T", f)
    check("mv11 ...and a real work-item id passes - the case that fails if "
          "the integer test is inverted", f == [], f)
    # PRE-EXISTING AND RECORDED RATHER THAN FIXED: `bool` is an `int` subclass,
    # so `"id": true` passes the integer test here, unlike `meta.version` in
    # `_check_meta`, which excludes bool by name. This case asserts the CURRENT
    # behaviour so the split cannot be blamed for it and a later fix has to
    # change a case on purpose rather than discover one.
    f = []
    M._check_ado({"ado": {"id": True}}, "task T", f)
    check("mv12 a boolean id is a finding: `bool` is an `int` subclass, so a "
          "check that only asks isinstance(x, int) accepts `true` as a work-item "
          "id - which `meta.version` already excluded by name, so the tree "
          "disagreed with itself about one question (F15)",
          any("integer work-item id" in x for x in f), f)
    # Both directions, because excluding bool is one line and over-excluding is
    # the same line: a real id must still pass, and `False` must fail like `True`.
    f_ok, f_false = [], []
    M._check_ado({"ado": {"id": 103205}}, "task T", f_ok)
    M._check_ado({"ado": {"id": False}}, "task T", f_false)
    check("mv12b ...while an actual integer id still passes, and `false` fails "
          "for the same reason `true` does",
          f_ok == [] and any("integer work-item id" in x for x in f_false),
          (f_ok, f_false))

    # --- the vocabulary, and the agreement about it ---
    check("mv13 STATUS carries both terminal words: `cancelled` is an answer, "
          "not a synonym for done",
          "done" in M.STATUS and "cancelled" in M.STATUS, M.STATUS)
    check("mv14 `TERMINAL` is NOT defined here - it is `_manifest_io`'s, and "
          "holding it would give this module an import, put it at layer 2 and "
          "push `_manifest_rules` past the layer its consumers leave free",
          not hasattr(M, "TERMINAL") and _rules.TERMINAL is _mio.TERMINAL, "")

    _shared = ("STATUS", "TESTS_MODE", "RISK", "BUG_STATUS", "BUG_ID_RE",
               "PROPOSAL_STATUS", "PROP_ID_RE", "KNOWN_ROOT", "KNOWN_META",
               "KNOWN_ADO", "KNOWN_PHASE", "CLAIM_KEYS", "KNOWN_TASK",
               "KNOWN_BUG", "KNOWN_PROPOSAL", "_strip_line_suffix",
               "_safe_list", "_require_fields", "_check_ado", "_unknown_keys")
    _forked = [n for n in _shared if getattr(_rules, n) is not getattr(M, n)]
    check("mv15 every name `_manifest_rules` re-exports from here IS this "
          "object - `is`, so a literal pasted back into the front door fails "
          "here instead of drifting from the table it was copied from: %r"
          % (_forked,), _forked == [])
    # The second direction, and it is not vacuous: mv15 also passes if a name
    # disappeared from BOTH files. This is the case that fails on that.
    _absent = [n for n in _shared if not hasattr(M, n)]
    check("mv16 ...and all %d of them still exist here - mv15 would pass over "
          "a name deleted from both sides: %r" % (len(_shared), _absent),
          _absent == [])

    # The four consumers, each pinned on the names it actually reads. A module
    # growing its own copy of `_unknown_keys` is the drift this catches.
    _cons = [("_manifest_ado", _ado, ("_unknown_keys", "STATUS", "BUG_STATUS",
                                      "KNOWN_ADO")),
             ("_manifest_typos", _typos, ("_safe_list",)),
             ("_manifest_crossrefs", _cross, ("_unknown_keys", "_safe_list",
                                              "_require_fields", "_check_ado",
                                              "_strip_line_suffix")),
             ("_manifest_phases", _phases, ("_unknown_keys", "_safe_list",
                                            "_require_fields", "_check_ado"))]
    _drift = [(mod, n) for mod, m, names in _cons for n in names
              if getattr(m, n) is not getattr(M, n)]
    check("mv17 all four layer-2 pieces read this module's objects rather "
          "than their own: %r" % (_drift,), _drift == [])

    # --- the agreement with the schema ---
    # The sets restate vocabulary `schema/audit-plan.schema.json` owns, and until
    # v0.40 nothing compared them: the schema could gain a property and the set
    # beside it stayed behind in silence, so the typo-catcher warned about a real
    # key. `_help.schema_vocab_drift()` is that comparison (it lives there because
    # the tree's one schema walk does - see this module's SCHEMA_ANCHORS comment).
    _levels = _help.schema_level_keys()
    _compared = sum(len(v) for v in _levels.values())
    check("mv18 every KNOWN_* set still agrees with audit-plan.schema.json - a "
          "field added to the schema and not here arrives BY NAME: %r"
          % (_help.schema_vocab_drift(),),
          _help.schema_vocab_drift() == [])
    # mv18 compares set differences, and a difference against an empty set is
    # empty. Without this the whole check would pass over a renamed $def.
    check("mv19 ...over %d schema properties at %d anchors, none of them zero - "
          "the count is the case, because 'no drift' over nothing compared reads "
          "exactly like agreement"
          % (_compared, len(_levels)),
          _compared >= 100 and len(_levels) == len(M.SCHEMA_ANCHORS)
          and not [n for n, keys in _levels.items() if not keys],
          repr(sorted((n, len(k)) for n, k in _levels.items())))
    check("mv20 every KNOWN_* set on this module is anchored, so one added later "
          "cannot opt out of mv18 by being forgotten",
          set(_help.vocab_sets(M)) == {n for n, _ in M.SCHEMA_ANCHORS},
          repr(sorted(set(_help.vocab_sets(M)) ^
                      {n for n, _ in M.SCHEMA_ANCHORS})))
    _exempt = [(name, key) for name, keys in M.OFF_SCHEMA.items()
               for key in keys
               if not str(keys[key]).strip()
               or key not in set(getattr(M, name, ()))
               or key in _levels.get(name, set())]
    check("mv21 all %d OFF_SCHEMA entries are LIVE - each names a key its set "
          "still holds, the schema still does not declare, and each carries a "
          "reason. An exemption list without live reasons is where a lint goes "
          "to die: %r" % (sum(len(v) for v in M.OFF_SCHEMA.values()), _exempt),
          _exempt == [])
    # Red-first against the REAL anchors rather than a fixture: the cases in
    # test__help.py prove the comparison, this one proves it is pointed at this
    # schema. Dropping a key from a COPY leaves the shipped set untouched.
    _cut = dict(_help.vocab_sets(M))
    _cut["KNOWN_ADO"] = set(M.KNOWN_ADO) - {"stateMap"}
    _cut_drift = _help.vocab_drift(_levels, _cut, M.SCHEMA_ANCHORS, M.OFF_SCHEMA)
    check("mv22 ...and dropping a real key from a copy of KNOWN_ADO names "
          "`meta.ado.stateMap` - the mutation that would otherwise be silent",
          [p for _, p in _cut_drift if "meta.ado.stateMap is in the schema" in p]
          and "stateMap" in M.KNOWN_ADO, repr(_cut_drift))

    # --- the recommended subsets, checked the other way round ---
    # `CLAIM_KEYS` restates schema vocabulary too, but it is a RECOMMENDED subset:
    # narrower than the schema by design, so mv18's coverage rule would fail it for
    # doing its job. `_help.schema_subset_drift()` asks only for containment - every
    # key in the tuple is a property the schema declares at `phases[].claim` - and
    # says nothing about the ones it omits.
    _slv = _help.schema_level_keys(None, M.SUBSET_ANCHORS)
    _sdrift = _help.schema_subset_drift()
    check("mv23 every recommended subset is still drawn from the schema - a key "
          "misspelled in one is asked of nothing and reported by nothing, so it "
          "arrives BY NAME instead: %r" % (_sdrift,), _sdrift == [])
    # The table itself is asserted non-empty BY NAME, not just self-consistent:
    # `len(_slv) == len(SUBSET_ANCHORS)` is 0 == 0 over an emptied table, and mv23
    # over no subsets at all is the same silence as mv23 over agreeing ones.
    check("mv24 ...over the %d properties audit-plan.schema.json declares at "
          "`phases[].claim` and the %d keys CLAIM_KEYS recommends, neither of them "
          "zero and the anchor table itself not empty - the counts are the SCOPE "
          "that makes mv23's silence worth anything, and the tuple's is the half "
          "that would otherwise PASS: an empty set contains nothing and asks for "
          "nothing" % (len(_slv.get("CLAIM_KEYS") or ()), len(M.CLAIM_KEYS)),
          "CLAIM_KEYS" in dict(M.SUBSET_ANCHORS)
          and len(_slv) == len(M.SUBSET_ANCHORS)
          and not [n for n, keys in _slv.items() if not keys]
          and not [n for n, _a in M.SUBSET_ANCHORS if not getattr(M, n, ())],
          repr(sorted((n, len(k)) for n, k in _slv.items())))
    # THE SECOND-DIRECTION CASE, and it is the one that looks vacuous and gets cut.
    # A guard that never fires is the original bug; a guard that ALWAYS fires is the
    # other wrong implementation, and only this fails on it. Narrowing a COPY of the
    # tuple further has to stay silent against the REAL schema, not just a fixture.
    # `.get`, not `[...]`: emptying SUBSET_ANCHORS is a mutation these cases must
    # FAIL on, and a KeyError here would take mv25-mv28 out of the run instead -
    # "did not run" is not "went red".
    _claim_lv = set(_slv.get("CLAIM_KEYS") or ())
    _omitted = sorted(_claim_lv - set(M.CLAIM_KEYS))
    _narrow = _help.subset_drift(_slv, {"CLAIM_KEYS": ("sessionId",)},
                                 M.SUBSET_ANCHORS)
    check("mv25 ...and omitting a property the schema declares is NOT drift: %r is "
          "written BY a claim rather than asked OF one, and a copy narrowed to a "
          "single key stays silent too - if this goes red the check has started "
          "demanding coverage, and a lint that fails the correct state gets routed "
          "around" % (_omitted,),
          _omitted == ["at"] and _narrow == [], repr(_narrow))
    check("mv26 every *_KEYS subset on this module is anchored, so one added later "
          "cannot opt out of mv23 by being forgotten",
          set(_help.vocab_subsets(M)) == {n for n, _ in M.SUBSET_ANCHORS},
          repr(sorted(set(_help.vocab_subsets(M)) ^
                      {n for n, _ in M.SUBSET_ANCHORS})))
    # Red-first against the REAL anchor, both directions, on COPIES - the shipped
    # tuple and the shipped schema are untouched, so the tree is never one exception
    # away from carrying the mutation.
    _typo = _help.subset_drift(_slv, {"CLAIM_KEYS": ("sessionID", "host", "branch")},
                               M.SUBSET_ANCHORS)
    _lost = dict(_slv)
    _lost["CLAIM_KEYS"] = _claim_lv - {"branch"}
    _gone = _help.subset_drift(_lost, _help.vocab_subsets(M), M.SUBSET_ANCHORS)
    _said = ("%s is recommended by this set and not declared by the schema - a typo "
             "here does not warn, it stops the key being asked for at all")
    check("mv27 ...and both mutations land, ONE problem each rather than at least "
          "one: misspelling `sessionId` in a copy of the tuple names "
          "`phases[].claim.sessionID`, and a schema that stops declaring `branch` "
          "names that - so the subset is checked against this document, not itself",
          [p for _, p in _typo] == [_said % ("phases[].claim.sessionID",)]
          and [p for _, p in _gone] == [_said % ("phases[].claim.branch",)]
          and "sessionId" in M.CLAIM_KEYS and "branch" in _claim_lv,
          repr((_typo, _gone)))
    # The subset check cannot see whether anything still READS the tuple; deleting
    # the loop in `_check_claim` would leave mv23 green over a set nobody consults.
    # So drive the warning for real, one key at a time.
    _full = {"sessionId": "s-1", "host": "h-1", "branch": "b-1", "at": "2026-01-01"}
    _unnamed = []
    for _k in M.CLAIM_KEYS:
        _claim = dict((k, v) for k, v in _full.items() if k != _k)
        _f, _w = [], []
        _phases._check_claim({"status": "in_progress", "claim": _claim}, "P1", _f, _w)
        if _f or len(_w) != 1 or _k not in _w[0]:
            _unnamed.append((_k, _f, _w))
    _f0, _w0 = [], []
    _phases._check_claim({"status": "in_progress", "claim": dict(_full)}, "P1",
                         _f0, _w0)
    check("mv28 ...and every key CLAIM_KEYS names is really asked of a claim: "
          "dropping each one in turn draws exactly one warning naming it at "
          "`_manifest_phases._check_claim`, and a complete claim draws none. This "
          "is the consequence mv23 protects, and mv23 cannot see it: %r"
          % (_unnamed,), _unnamed == [] and (_f0, _w0) == ([], []))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_vocab.py --selftest\n")
    raise SystemExit(2)
