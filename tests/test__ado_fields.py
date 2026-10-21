#!/usr/bin/env python3
"""
The cases for `_ado_fields.py` — what this project SUPPLIES to a board's fields.

`_ado_conventions` can only refuse, and the connector could only send title,
description, state, area, iteration, tags and a parent link. So the honest
`conventions` block for a governed board gated out every CREATE and the block
that let a push through was a weakened description of the board — the gate could
not supply and the connector could not conform. The case that carries this whole
module is `af23`: a `requiredFields` rule that REFUSES the bare payload and
passes the merged one, with both halves asserted, so it cannot go green because
conformance broke.

EVERY RULE IS PINNED IN BOTH DIRECTIONS. A refusal that never fires is the
original bug; a refusal that always fires is the other wrong implementation, and
the case that catches it looks vacuous (`af0`: a well-formed template produces
nothing at all). Both are here on purpose, and `af10` is the third: a legitimate
custom field whose last dotted segment collides with a reserved one must NOT be
refused, which is what makes the whole-string comparison a decision rather than
an accident.

THE TABLES ARE MEASURED, NOT INVENTED. The read-only set and the two-spellings
rule come from a live board (test-audit-lab / audit-gate-agile, 2026-08-24) —
the module docstring carries the command that re-derives them and the two
different ways ADO reports a read-only write. A hand-written fixture agreeing
with a hand-written table would prove nothing about either.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import io
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402
import _ado_fields as M                            # noqa: E402
import _ado_conventions as _conv                   # noqa: E402
import _manifest_ado as _ado                       # noqa: E402


# A template modelled on what a real governed board asks for: measured against
# audit-gate-agile, a Task carries Activity and Original Estimate and a User
# Story carries Story Points, and neither type carries the other's fields.
TEMPLATE = {
    "Task": {"Microsoft.VSTS.Common.Activity": "Development",
             "Microsoft.VSTS.Scheduling.OriginalEstimate": 4},
    "User Story": {"Microsoft.VSTS.Scheduling.StoryPoints": 3},
}


def _payload(**over):
    """A create payload the connector really could build today."""
    item = {"type": "Task",
            "fields": {"System.Title": "[T1.2] Merge refactored code",
                       "System.Description": "Done when: CI green.",
                       "System.Tags": "audit-plugin"},
            "parent": 103205}
    fields = over.pop("fields", None)
    if fields is not None:
        item["fields"].update(fields)
    item.update(over)
    return item


def _findings(block):
    return M.check_fields_config(block)[0]


def _warnings(block):
    return M.check_fields_config(block)[1]


def _naming(lines, needle):
    """How many of these lines name `needle`. Counted, not found: a rule that
    fired twice for one key and a rule that fired once read identically to
    `any()`, and the whole subject here is a rule firing the right number of
    times."""
    return len([x for x in lines if needle in x])


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the two directions of "does the refusal fire" ------------------------
    # THE VACUOUS-LOOKING ONE, KEPT ON PURPOSE. It passes on an implementation
    # with no checks at all, and it is the only case that fails when a refusal
    # becomes unconditional - which is the other wrong way to write this module.
    _f, _w = M.check_fields_config(TEMPLATE)
    check("af0 a template naming only fields the connector leaves alone passes "
          "clean - no finding AND no warning: f=%r w=%r" % (_f, _w),
          _f == [] and _w == [])
    check("af1 absent and null are the same answer and both are silent - this "
          "key is new, so every existing manifest is exactly this case",
          M.check_fields_config(None) == ([], []))

    # --- the block's own shape ------------------------------------------------
    check("af2 a wrong TYPE for the block is a finding, because it would be "
          "misread: %r" % (_findings([]),),
          len(_findings([])) == 1 and _naming(_findings([]), "keyed by work "
                                              "item type name") == 1)
    check("af3 a type whose template is not an object is a finding naming that "
          "type and no other: %r" % (_findings({"Task": ["a"]}),),
          len(_findings({"Task": ["a"]})) == 1
          and _naming(_findings({"Task": ["a"]}), "meta.ado.fields.Task") == 1)
    check("af4 an EMPTY block is a warning and not a finding - it configures "
          "nothing, which is the silence worth naming rather than a config that "
          "would be misread",
          _findings({}) == [] and len(_warnings({})) == 1)
    check("af5 ...and so is an empty template for one type, which is the same "
          "silence one level down",
          _findings({"Task": {}}) == []
          and _naming(_warnings({"Task": {}}), "meta.ado.fields.Task") == 1)
    _bad_key = {"": {"X.Y": 1}}
    check("af6 a type key that is not a work item type NAME is a finding - the "
          "vocabulary is meta.ado.types', not this file's own: %r"
          % (_findings(_bad_key),),
          len(_findings(_bad_key)) == 1)

    # --- a field the connector already maps -----------------------------------
    _title = {"Task": {"System.Title": "whatever"}}
    check("af7 a field the connector itself maps is REFUSED at validation, not "
          "warned about at push: a config that cannot do what it says is better "
          "caught when it is written: %r" % (_findings(_title),),
          len(_findings(_title)) == 1
          and _naming(_findings(_title), "System.Title") == 1)
    # The reason travels with the refusal, because "you may not set this" with
    # no pointer sends the reader back to the schema to guess which key does.
    _state = {"Task": {"System.State": "Active"}}
    check("af8 ...and the refusal names the manifest key that DOES decide it, "
          "so the reader is not sent to guess: %r" % (_findings(_state),),
          _naming(_findings(_state), "meta.ado.stateMap") == 1)
    _display = {"Task": {"Title": "whatever"}}
    check("af9 the DISPLAY spelling is refused too - ADO resolved "
          "`--fields Activity=…` onto Microsoft.VSTS.Common.Activity on a live "
          "board, so one spelling checked is a hole the size of the other: %r"
          % (_findings(_display),),
          len(_findings(_display)) == 1
          and _naming(_findings(_display), "System.Title") == 1)

    # --- a field ADO will not accept ------------------------------------------
    _parent = {"Task": {"System.Parent": 103205}}
    check("af10 a readOnly field is refused with the reason, never attempted: "
          "%r" % (_findings(_parent),),
          len(_findings(_parent)) == 1
          and _naming(_findings(_parent), "readOnly") == 1)
    check("af11 ...and the reason is the MEASURED one - a System.Parent create "
          "reports success and leaves no parent, so 'attempt it and report what "
          "ADO said' would report a create that worked",
          _naming(_findings(_parent), "leaves no parent") == 1)
    check("af12 the display spelling of a readOnly field is refused too",
          len(_findings({"Task": {"Parent": 103205}})) == 1)
    check("af13 System.Parent is in the read-only table under both spellings, "
          "which is what af12 depends on rather than assuming",
          ("System.Parent", "Parent") in M.READ_ONLY)

    # --- the case that makes the comparison a DECISION ------------------------
    # A last-dotted-segment rule would refuse both of these, and both are legal
    # fields somebody can own. Without this case the whole-string comparison
    # could be replaced by a segment one and nothing would go red.
    _custom = {"Task": {"Custom.Severity": "high", "Custom.Title": "x"}}
    check("af14 a custom field whose last segment collides with a reserved one "
          "is NOT refused - the comparison is whole-string, and a segment rule "
          "would take somebody's real field away: %r" % (M.check_fields_config(
              _custom),),
          M.check_fields_config(_custom) == ([], []))

    # --- values ---------------------------------------------------------------
    _ok_values = {"Task": {"A.B": "text", "A.C": 4, "A.D": 1.5, "A.E": True}}
    check("af15 a string, an int, a float and a boolean are all literals ADO "
          "takes: %r" % (M.check_fields_config(_ok_values),),
          M.check_fields_config(_ok_values) == ([], []))
    _bad_values = {"Task": {"A.B": None, "A.C": ["x"], "A.D": {"x": 1},
                            "A.E": "   "}}
    check("af16 null, a list, an object and a blank string are each a finding - "
          "counted, because a rule that fired once for four keys and a rule "
          "that fired for each read the same to any(): %r"
          % (_findings(_bad_values),),
          len(_findings(_bad_values)) == 4)
    check("af17 ...and the blank one says WHY it is not merely ugly: "
          "conventions treat empty as missing, so it would validate and still "
          "be refused at push",
          _naming(_findings({"Task": {"A.B": ""}}), "requiredFields") == 1)
    _ph = {"Task": {"A.B": "{taskId}"}}
    check("af18 a value that LOOKS like a placeholder is a warning, not a "
          "finding: there is no substitution language, so it is written to the "
          "board literally and the silence is what would be the bug: %r"
          % (M.check_fields_config(_ph),),
          _findings(_ph) == [] and len(_warnings(_ph)) == 1
          and _naming(_warnings(_ph), "LITERALLY") == 1)

    # --- the carve-out, and its warning ---------------------------------------
    _rw = "Microsoft.VSTS.Scheduling.RemainingWork"
    check("af19 Remaining Work is NOT reserved - the connector writes it at "
          "DONE via onComplete and never at create, and a board that requires "
          "it at create is the case this module exists for",
          M.check_fields_config({"Task": {_rw: 2}}) == ([], [])
          and _rw not in [row[0] for row in M.RESERVED])
    _with_oc = {"fields": {"Task": {_rw: 2}},
                "onComplete": {"remainingWork": 0}}
    check("af20 ...and the overwrite at done is named at authoring time, as a "
          "warning: both keys are legal, the pushed value just does not survive "
          "completion: %r" % (M.template_contradictions(_with_oc),),
          len(M.template_contradictions(_with_oc)) == 1)
    # 0 is a real Remaining Work value and the commonest one, so a truthiness
    # test here would go silent on exactly the config that has the conflict.
    check("af21 ...proven against remainingWork=0, which a truthiness test "
          "would have read as 'not set' and skipped",
          M.template_contradictions(_with_oc)
          != M.template_contradictions({"fields": {"Task": {_rw: 2}},
                                        "onComplete": {"remainingWork": None}}))
    check("af22 null onComplete.remainingWork means the field is never touched, "
          "so there is no second write and nothing to warn about",
          M.template_contradictions({"fields": {"Task": {_rw: 2}},
                                     "onComplete": {"remainingWork": None}})
          == [])
    for _label, _ado_block in (("no fields block", {"onComplete": {}}),
                               ("no onComplete", {"fields": TEMPLATE}),
                               ("neither", {}),
                               ("a template that names something else",
                                {"fields": TEMPLATE,
                                 "onComplete": {"remainingWork": 0}})):
        check("af23 no overwrite warning for %s - a warning people learn to "
              "skip is how a real one gets missed" % (_label,),
              M.template_contradictions(_ado_block) == [],
              repr(M.template_contradictions(_ado_block)))

    # --- the merge ------------------------------------------------------------
    _in = _payload()
    _before = copy.deepcopy(_in)
    _res = M.merge_template(_in, TEMPLATE)
    check("af24 the merge returns a NEW payload and leaves the caller's dict "
          "alone - two contracts on one dict is how a caller comes to rely on "
          "the wrong one",
          _in == _before and _res["item"] is not _in
          and _res["item"]["fields"] is not _in["fields"])
    check("af25 ...and what it added is exactly this type's template: %r"
          % (_res["added"],),
          _res["added"] == TEMPLATE["Task"]
          and _res["item"]["fields"]["Microsoft.VSTS.Common.Activity"]
          == "Development"
          and _res["item"]["fields"]["System.Title"] == _before["fields"][
              "System.Title"])
    check("af26 ...and the value keeps its TYPE: an Original Estimate that "
          "arrived as a number must not leave as a string",
          _res["item"]["fields"]["Microsoft.VSTS.Scheduling.OriginalEstimate"]
          == 4)

    # THE NEGATIVE CASE: the merge must not fire when it should not.
    _story = M.merge_template(_payload(type="User Story"), TEMPLATE)
    check("af27 a type gets ITS OWN template and no other's - a Story does not "
          "collect the Task's Activity: %r" % (_story["added"],),
          _story["added"] == TEMPLATE["User Story"]
          and "Microsoft.VSTS.Common.Activity" not in _story["item"]["fields"])
    _none = M.merge_template(_payload(type="Bug"), TEMPLATE)
    check("af28 ...and a type the template says nothing about gets nothing at "
          "all, with the payload handed back unchanged",
          _none["added"] == {} and _none["skipped"] == {}
          and _none["item"]["fields"] == _payload(type="Bug")["fields"])
    _absent = M.merge_template(_payload(), None)
    check("af29 no block at all is today's behaviour EXACTLY, as an equality a "
          "script can check rather than a sentence: the payload out equals the "
          "payload in",
          _absent["item"] == _payload() and _absent["added"] == {})

    # A collision here can only be a payload field this module's table does not
    # list yet - validation refuses the ones it does. Dropping it quietly would
    # hand back a payload the caller believes carries its template.
    _clash = M.merge_template(_payload(fields={"Custom.Owner": "connector"}),
                              {"Task": {"Custom.Owner": "template"}})
    check("af30 the template never overrides a field the payload already "
          "carries, and the skip is REPORTED rather than dropped: %r"
          % (_clash,),
          _clash["item"]["fields"]["Custom.Owner"] == "connector"
          and _clash["skipped"] == {"Custom.Owner": "template"}
          and _clash["added"] == {})
    # The spelling pair the tables DO know, which is every field the connector
    # can put in a payload. `Title` and `System.Title` are one field on the
    # board, so they have to be one field here.
    _spelt = M.merge_template(_payload(), {"Task": {"Title": "template"}})
    check("af31 ...and a payload field is recognised under the OTHER spelling "
          "of its name, so one ADO field cannot be merged in twice: %r"
          % (_spelt,),
          _spelt["added"] == {} and _spelt["skipped"] == {"Title": "template"}
          and _spelt["item"]["fields"]["System.Title"]
          == _payload()["fields"]["System.Title"])
    # The honest limit, stated as a case rather than left to a comment. Learning
    # that `Activity` and `Microsoft.VSTS.Common.Activity` are one field needs
    # the project's field catalogue, which an offline validator does not have,
    # and guessing by last dotted segment is what af14 forbids. Nothing is lost:
    # a create carrying one field under two spellings is refused by ADO out loud
    # (VS403691, measured 2026-08-24), so the pair this cannot see is the pair
    # the board will not accept either.
    _untabled = M.merge_template(_payload(fields={"Activity": "connector"}),
                                 {"Task": {
                                     "Microsoft.VSTS.Common.Activity": "t"}})
    check("af31b ...while a pair NEITHER table knows is left alone rather than "
          "guessed at, which is the price of af14 and is paid loudly by ADO "
          "(VS403691) rather than quietly here",
          _untabled["skipped"] == {}
          and len(_untabled["added"]) == 1)

    # --- THE case this module exists for --------------------------------------
    # Both halves are asserted, so it cannot pass because conformance broke: the
    # bare payload must really be refused, and the merged one must really pass.
    _board = {"requiredFields": {
        "Task": ["Microsoft.VSTS.Common.Activity",
                 "Microsoft.VSTS.Scheduling.OriginalEstimate"]}}
    _bare = _conv.conformance_violations(_payload(), _board)
    _merged = _conv.conformance_violations(
        M.merge_template(_payload(), TEMPLATE)["item"], _board)
    check("af32 a requiredFields rule that REFUSES the payload the connector "
          "can build is satisfied by the template - which is the whole feature: "
          "bare=%r merged=%r" % (_bare, _merged),
          len(_bare) == 2 and _merged == [])

    # --- the front doors ------------------------------------------------------
    check("af33 `fields` is a known meta.ado key, so it does not arrive as a "
          "did-you-mean warning about itself",
          "fields" in _ado.KNOWN_ADO)
    _mf, _mw = _ado.check_ado_meta({"fields": {"Task": {"System.Title": "x"}}})
    check("af34 check_ado_meta grades the block THROUGH this module - the same "
          "sentence, not a second opinion about which names are legal",
          _mf == _findings({"Task": {"System.Title": "x"}}) and _mw == [])
    _cf, _cw = _ado.check_ado_meta({"fields": {"Task": {_rw: 2}},
                                    "onComplete": {"remainingWork": 0}})
    check("af35 ...and the overwrite warning reaches the front door too, so the "
          "panel's PUT /api/ado sees it as well as the CLI: %r" % (_cw,),
          _cf == [] and _naming(_cw, "does not survive completion") == 1)

    # --- the panel, which has no control for this key yet ---------------------
    # The claim is that a hand-written template survives a connector save. It
    # rests on the card cloning the WHOLE saved object into its draft, so pin
    # that line: without it, every save would silently drop the key.
    _card = os.path.join(_output.SCRIPTS_DIR, "ui", "panel", "ado-connector.js")
    _src = io.open(_card, encoding="utf-8").read()
    check("af36 the connector card deep-copies the saved meta.ado into its "
          "draft, which is the only reason a hand-written meta.ado.fields "
          "survives a panel save while no control edits it",
          _src.count("ADRAFT=saved===null?null:JSON.parse(JSON.stringify(saved))")
          == 1)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_fields.py --selftest\n")
    raise SystemExit(2)
