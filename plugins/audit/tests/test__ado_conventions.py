#!/usr/bin/env python3
"""
The cases for `_ado_conventions.py` — what a work item must look like to belong.

The module exists because the connector could always write a CORRECT work item
and could not write a CONFORMING one, and because that gap survived a live ADO
gate: the gate ran against two empty throwaway projects on stock templates, so
it proved protocol and could not prove fit. These cases are the fit.

Two halves, and both are pinned. `check_conventions_config` grades the block
somebody wrote — wrong TYPE is a finding, unknown KEY is a did-you-mean warning,
the same line `_manifest_ado` draws. `conformance_violations` grades an item
against it, and its cases are written from a real board's standard (a mandatory
"Done when", acceptance criteria on stories, a closed tag vocabulary, a parent)
rather than from what was convenient to implement.

THE SILENCE IS A CASE. An absent `conventions` block means the board has no
standard, so every item conforms — and that has to be pinned, because a checker
that refused items on a board with no rules would be switched off within a day,
which is how a conformance check dies.

Every rule is also pinned NEGATIVELY. A required-field check that passes an item
missing the field, or a vocabulary that admits a tag outside it, is a check that
asserts nothing — and this file's whole subject is a check that asserted nothing
until a client board disagreed with it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_conventions as M                       # noqa: E402
import _manifest_ado as _ado                       # noqa: E402


# A board standard modelled on a real one, so the cases are not shaped by what
# was easy: Uptimize / factory-scitara-ic-nreg-ec1, whose own script enforces a
# skeleton, a "Done when", acceptance criteria on stories, a closed tag
# vocabulary and a parent.
BOARD = {
    "requiredFields": {
        "Task": ["Microsoft.VSTS.Scheduling.RemainingWork"],
        "User Story": ["Microsoft.VSTS.Common.AcceptanceCriteria"],
    },
    "descriptionMustContain": {
        "Task": ["Done when"],
        "User Story": ["Done when"],
    },
    "tagVocabulary": {
        "type": ["refactor", "feature", "qa"],
        "supplier": ["databridge"],
    },
    "requireParent": True,
}


def _task(**over):
    """A Task that conforms to BOARD, so each case can break exactly one thing."""
    item = {"type": "Task",
            "fields": {"System.Title": "Merge refactored code to main",
                       "System.Description": "Purpose: merge.\nDone when: CI green.",
                       "System.Tags": "type:refactor; supplier:databridge",
                       "Microsoft.VSTS.Scheduling.RemainingWork": 2},
            "parent": 103205}
    fields = over.pop("fields", None)
    if fields is not None:
        item["fields"].update(fields)
    item.update(over)
    return item


# --- cases --------------------------------------------------------------------
def _cases(check):
    # The baseline every negative case is measured against. Without this, a
    # fixture that violated something incidentally would make every case below
    # pass for the wrong reason.
    check("ac0 the fixture conforms, so each case below fails for the one thing "
          "it breaks and not for a fourth thing nobody noticed",
          M.conformance_violations(_task(), BOARD) == [],
          repr(M.conformance_violations(_task(), BOARD)))

    # --- the silence ----------------------------------------------------------
    check("ac1 no conventions block means the board has no standard, so every "
          "item conforms - NOT 'could not check'",
          M.conformance_violations(_task(), None) == []
          and M.conformance_violations({"type": "Task"}, {}) == [])
    check("ac2 ...and an item that would fail every rule still conforms when "
          "there is no rule, which is what stops this being switched off",
          M.conformance_violations({"type": "Task", "fields": {}}, {}) == [])

    # --- required fields ------------------------------------------------------
    _v = M.conformance_violations(
        _task(fields={"Microsoft.VSTS.Scheduling.RemainingWork": None}), BOARD)
    check("ac3 a required field that is missing is named, with the field's "
          "reference name so it can be acted on: %r" % (_v,),
          len(_v) == 1 and "RemainingWork" in _v[0])
    _v = M.conformance_violations(
        _task(fields={"Microsoft.VSTS.Scheduling.RemainingWork": "   "}), BOARD)
    check("ac4 ...and whitespace is not a value - an empty box satisfies the "
          "schema and not the board",
          len(_v) == 1 and "RemainingWork" in _v[0], repr(_v))
    # Scoped BY TYPE: a Task does not owe a story's acceptance criteria.
    check("ac5 a rule scoped to another type does not fire here - a checker that "
          "demanded acceptance criteria on a task would be turned off",
          all("AcceptanceCriteria" not in x
              for x in M.conformance_violations(_task(), BOARD)))
    _story = {"type": "User Story",
              "fields": {"System.Description": "Done when: filters work.",
                         "System.Tags": "type:feature"},
              "parent": 103204}
    _v = M.conformance_violations(_story, BOARD)
    check("ac6 ...and it DOES fire on the type it is scoped to: %r" % (_v,),
          any("AcceptanceCriteria" in x for x in _v))

    # --- the description skeleton --------------------------------------------
    _v = M.conformance_violations(
        _task(fields={"System.Description": "Purpose: merge."}), BOARD)
    check("ac7 a description without the board's marker is named - 'Done when' "
          "is the one line their standard will not do without: %r" % (_v,),
          len(_v) == 1 and "Done when" in _v[0])
    check("ac8 ...and the marker match is case-insensitive, because a skeleton "
          "written 'DONE WHEN:' is the same skeleton",
          M.conformance_violations(
              _task(fields={"System.Description": "DONE WHEN: CI green."}),
              BOARD) == [])

    # --- the tag vocabulary ---------------------------------------------------
    _v = M.conformance_violations(
        _task(fields={"System.Tags": "type:refactor; area:dashboard"}), BOARD)
    check("ac9 a tag whose PREFIX is outside the vocabulary is named, and the "
          "message lists what is allowed: %r" % (_v,),
          len(_v) == 1 and "area" in _v[0] and "supplier" in _v[0])
    _v = M.conformance_violations(
        _task(fields={"System.Tags": "type:chore; supplier:databridge"}), BOARD)
    check("ac10 a known prefix with an unknown VALUE is a different finding - "
          "the two fail for different reasons and say so: %r" % (_v,),
          len(_v) == 1 and "chore" in _v[0] and "allowed" in _v[0])
    _v = M.conformance_violations(
        _task(fields={"System.Tags": "type:refactor; FE"}), BOARD)
    check("ac11 a bare tag is refused unless the board opted into free-form, "
          "and the message says how to opt in: %r" % (_v,),
          len(_v) == 1 and '"*"' in _v[0])
    _free = dict(BOARD)
    _free["tagVocabulary"] = dict(BOARD["tagVocabulary"], **{"*": []})
    check("ac12 ...and with `*` present the same bare tag passes, so the escape "
          "hatch is spelled rather than implied",
          M.conformance_violations(
              _task(fields={"System.Tags": "type:refactor; FE"}), _free) == [])
    # `;` is the field's own separator and the round-trip leaves spaces behind.
    check("ac13 tags split on ';' with surrounding space ignored, which is what "
          "System.Tags round-trips to",
          M.split_tags(" a ;b;; c ") == ["a", "b", "c"]
          and M.split_tags("") == [] and M.split_tags(None) == [])

    # --- the parent -----------------------------------------------------------
    _v = M.conformance_violations(_task(parent=None), BOARD)
    check("ac14 an item with no parent is refused when the board requires one - "
          "audit work belongs INSIDE the backlog, not beside it: %r" % (_v,),
          len(_v) == 1 and "parent" in _v[0])
    check("ac15 ...and 0 and '' are not work item ids, while a string id is one",
          len(M.conformance_violations(_task(parent=0), BOARD)) == 1
          and len(M.conformance_violations(_task(parent=""), BOARD)) == 1
          and M.conformance_violations(_task(parent="103205"), BOARD) == [])
    _noparent = dict(BOARD)
    _noparent.pop("requireParent")
    check("ac16 a board that does not require a parent does not get the finding",
          M.conformance_violations(_task(parent=None), _noparent) == [])

    # --- the config half ------------------------------------------------------
    _f, _w = M.check_conventions_config(None)
    check("ac17 an absent conventions block is legal and silent - an optional "
          "feature nobody configured must not nag", _f == [] and _w == [])
    _f, _w = M.check_conventions_config(BOARD)
    check("ac18 a well-formed block passes clean: f=%r w=%r" % (_f, _w),
          _f == [] and _w == [])
    _f, _w = M.check_conventions_config({"requiredFields": ["Task"]})
    check("ac19 a wrong TYPE is a finding, because it would be misread: %r"
          % (_f,), any("must be an object" in x for x in _f))
    _f, _w = M.check_conventions_config({"requireParent": "yes"})
    check("ac20 ...including a string where a boolean decides whether the rule "
          "runs at all: %r" % (_f,), any("true or false" in x for x in _f))
    _f, _w = M.check_conventions_config({"tagVocabluary": {}})
    check("ac21 an unknown KEY is a did-you-mean warning and not a finding - it "
          "configures nothing, and that silence is the thing to name: %r"
          % (_w,), _f == [] and any("tagVocabluary" in x for x in _w))
    _f, _w = M.check_conventions_config({"tagVocabulary": {}})
    check("ac22 an EMPTY vocabulary forbids every tag, which is almost never "
          "meant - warned rather than silently enforced: %r" % (_w,),
          any("forbids every tag" in x for x in _w))

    # --- one front door -------------------------------------------------------
    # `_manifest_ado.check_ado_meta` must reach this module's objects rather than
    # carry a second copy of the rules, for the same reason it reads
    # `_manifest_vocab`'s: two implementations are two answers.
    _f, _w = _ado.check_ado_meta({"conventions": {"requireParent": "yes"}})
    check("ac23 check_ado_meta grades the conventions block through THIS module, "
          "so the CLI and the panel cannot disagree about it: %r" % (_f,),
          any("true or false" in x for x in _f))
    # --- parentWorkItem: the other half of "inside the backlog, not beside it" --
    _f, _w = _ado.check_ado_meta({"parentWorkItem": 103205})
    check("ac25 a positive integer id is legal", _f == [] and _w == [])
    _f, _w = _ado.check_ado_meta({"parentWorkItem": None})
    check("ac26 ...and null is an answer - the connector builds its own branch",
          _f == [] and _w == [])
    _f, _w = _ado.check_ado_meta({"parentWorkItem": "103205"})
    check("ac27 a STRING id is a finding rather than something coerced: a quoted "
          "number is a typo, and coercing it would hide the one thing worth "
          "saying: %r" % (_f,), any("integer" in x for x in _f))
    _f, _w = _ado.check_ado_meta({"parentWorkItem": 0})
    check("ac28 ...and 0 is not a work item id: %r" % (_f,),
          any("positive" in x for x in _f))
    # `True` is an int in Python, and a config that said `true` here would sail
    # through an isinstance check that forgot it.
    _f, _w = _ado.check_ado_meta({"parentWorkItem": True})
    check("ac29 ...nor is `true`, which Python would otherwise accept as the "
          "integer 1: %r" % (_f,), any("integer" in x for x in _f))
    check("ac30 `parentWorkItem` is a known meta.ado key",
          "parentWorkItem" in _ado.KNOWN_ADO)

    check("ac24 ...and `conventions` is a known meta.ado key, so it does not "
          "arrive as a did-you-mean warning about itself",
          "conventions" in _ado.KNOWN_ADO)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_conventions.py --selftest\n")
    raise SystemExit(2)
