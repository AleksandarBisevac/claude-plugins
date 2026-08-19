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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_vocab.py --selftest\n")
    raise SystemExit(2)
