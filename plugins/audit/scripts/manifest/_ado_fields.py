#!/usr/bin/env python3
"""
`meta.ado.fields` - what THIS project SUPPLIES to a governed board's fields.

`_ado_conventions` is the other half and it can only REFUSE. The connector's
create payload is title, description, state, area, iteration, tags and a parent
link (`RemainingWork` only at done, via `onComplete`), so on a board whose Task
really owes `Microsoft.VSTS.Common.Activity` and
`Microsoft.VSTS.Scheduling.OriginalEstimate` there was no way to supply
anything else. The honest `conventions` block refused every CREATE and the
block that let a push through was a deliberately weakened description of the
board. The gate could only refuse and the connector could not supply, so on
exactly the boards the feature was designed for nothing could be created.

This module is the supply side: a per-work-item-type template merged into the
payload BEFORE the conformance check runs. The board states what it requires,
the manifest states what this project supplies, and the gate grades the result.

KEYED BY WORK ITEM TYPE NAME, matching how `types.{bug,task,pbi}` resolve, so a
board that renames its types is configured in one vocabulary rather than two.

VALUES ARE LITERALS AND THERE IS NO SUBSTITUTION LANGUAGE, which is a decision
and not an omission. The fields a template is for are board-governance
constants - an Activity, an estimate, a story-point default. The fields where
the manifest's OWN data belongs (title, description, tags) are exactly the ones
`RESERVED` forbids, so a `{taskId}` would only ever write manifest data into a
field the connector does not map - and that is a change to the connector's
mapping table, not something a config key should be able to invent. Supporting
it would also force every literal to grow a brace escape and every value to
become a string, when `OriginalEstimate` has to stay a number. A value that
LOOKS like a placeholder is warned about rather than expanded, because writing
`{taskId}` onto a board is visible garbage and the silence is the bug.

TWO SPELLINGS REACH ONE FIELD, WHICH IS MEASURED AND NOT ASSUMED. Against
test-audit-lab / audit-gate-agile on 2026-08-24,
`az boards work-item create --fields "Activity=Development"` produced an item
carrying `Microsoft.VSTS.Common.Activity`: ADO resolves a DISPLAY name as
readily as a reference name. So every table here carries both spellings and
`_norm` compares the whole string, never a last-dotted-segment guess - a guess
would refuse a perfectly legal `Custom.Severity` for colliding with
`Microsoft.VSTS.Common.Severity`.

WHY A READ-ONLY FIELD IS REFUSED HERE INSTEAD OF ATTEMPTED. The same session
sent `System.Parent`, `System.Id` and `System.CreatedBy` through `--fields`.
Every one of those creates SUCCEEDED, and every resulting item came back with
the field unset and no relation - a silent no-op reported as success. Only
`System.BoardColumn` refused out loud (`TF401326: Invalid field status
'ReadOnly'`). So for the field people most want to set, validation here is the
only thing that can say anything at all; "attempt it and report what ADO said"
would report a create that worked and a parent that is not there. Re-derive the
table with:

  az devops invoke --organization https://dev.azure.com/<org> --area wit \
    --resource fields --api-version 7.1 --http-method GET

and keep the entries whose `readOnly` is true. The agile and scrum lab projects
returned identical sets; the organization-wide list adds the link/form internals
below, which are read-only everywhere.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_fields.py` - see
`plugins/audit/tests/_harness.py`.
"""
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

# --- the two tables a template may not name --------------------------------------

# Fields the CONNECTOR itself computes, each with the manifest key that decides
# it. A template winning over one of these would make `commands/sync.md`'s
# mapping table a lie, and losing to one silently would make the config a lie -
# so naming one is refused at VALIDATION time. A config that cannot do what it
# says is better caught when it is written than when it is pushed.
#
# `Microsoft.VSTS.Scheduling.RemainingWork` is deliberately ABSENT. The connector
# writes it only at DONE and only when `meta.ado.onComplete` is present, never at
# create - and a governed board that requires it at create is the exact case this
# module exists for. `template_contradictions` warns about the later overwrite
# instead, because that is what it is: a second moment, not a collision.
#
# Severity and Repro Steps stay in, and it costs nothing measurable: on the lab's
# agile process `workitemtypesfield` reports both on Bug alone, which is the one
# type the connector maps them for.
RESERVED = (
    ("System.Title", "Title",
     "the connector writes the manifest title (with its id prefix)"),
    ("System.Description", "Description",
     "the connector writes the manifest description"),
    ("Microsoft.VSTS.TCM.ReproSteps", "Repro Steps",
     "the connector writes a bug's repro/expected/actual here"),
    ("Microsoft.VSTS.Common.Severity", "Severity",
     "the connector maps bug.severity"),
    ("System.State", "State",
     "state is applied by UPDATE through meta.ado.stateMap"),
    ("System.AreaPath", "Area Path", "meta.ado.areaPath decides it"),
    ("System.IterationPath", "Iteration Path",
     "meta.ado.sprint, else meta.ado.iterationPath, decides it"),
    ("System.Tags", "Tags",
     "meta.ado.tag is read-merge-written onto the item's own tags, never "
     "wholesale"),
    ("System.WorkItemType", "Work Item Type",
     "meta.ado.types decides it, and it is this template's own key"),
    ("System.AssignedTo", "Assigned To",
     "commands/sync.md guarantees no silent assignment - push ASKS before "
     "every --assigned-to, using meta.ado.identityMap"),
)

# Fields ADO reports as `readOnly`. Setting one through `--fields` either refuses
# out loud or, worse, succeeds and does nothing - see the module docstring for
# both measurements.
READ_ONLY = (
    ("System.AttachedFileCount", "Attached File Count"),
    ("System.AuthorizedAs", "Authorized As"),
    ("System.AuthorizedDate", "Authorized Date"),
    ("System.BoardColumn", "Board Column"),
    ("System.BoardColumnDone", "Board Column Done"),
    ("System.BoardLane", "Board Lane"),
    ("System.ChangedDate", "Changed Date"),
    ("System.CommentCount", "Comment Count"),
    ("System.CreatedBy", "Created By"),
    ("System.CreatedDate", "Created Date"),
    ("System.ExternalLinkCount", "External Link Count"),
    ("System.HyperLinkCount", "Hyperlink Count"),
    ("System.Id", "ID"),
    ("System.Links.LinkType", "Link Type"),
    ("System.NodeName", "Node Name"),
    ("System.NodeType", "Node Type"),
    ("System.Parent", "Parent"),
    ("System.ProjectId", "ProjectID"),
    ("System.RelatedLinkCount", "Related Link Count"),
    ("System.RemoteLinkCount", "Remote Link Count"),
    ("System.Rev", "Rev"),
    ("System.RevisedDate", "Revised Date"),
    ("System.Watermark", "Watermark"),
    ("System.WorkItemForm", "Work Item Form"),
    ("System.WorkItemFormId", "Work Item FormID"),
)

# The field the connector writes at DONE rather than at create - named once,
# because the carve-out above and the warning below must not drift apart.
LATE_WRITTEN = ("Microsoft.VSTS.Scheduling.RemainingWork", "Remaining Work")


def _norm(name):
    """One key for the two spellings ADO accepts for one field.

    Whole-string, lowercased, with spaces and underscores dropped: `Area Path`
    and `System.AreaPath` collapse together, while `Custom.Severity` stays
    distinct from `Microsoft.VSTS.Common.Severity`. A last-segment rule would
    refuse that custom field, which is a real one somebody could own.
    """
    return "".join(str(name).split()).replace("_", "").lower()


def _lookup(rows):
    """{normalised spelling: the row}, both spellings pointing at one row."""
    out = {}
    for row in rows:
        out[_norm(row[0])] = row
        out[_norm(row[1])] = row
    return out


_RESERVED_BY_SPELLING = _lookup(RESERVED)
_READ_ONLY_BY_SPELLING = _lookup(READ_ONLY)
_LATE_SPELLINGS = (_norm(LATE_WRITTEN[0]), _norm(LATE_WRITTEN[1]))


def _canonical(name):
    """One key per ADO FIELD, where that is knowable without a network.

    `_norm` collapses the two ways of writing one name; this collapses the two
    NAMES of one field, but only for the fields the tables above carry. There is
    no offline way to learn that `Activity` and `Microsoft.VSTS.Common.Activity`
    are the same field - that lives in the project's field catalogue - and a
    guess (last dotted segment) would fuse `Custom.Severity` onto the stock
    Severity, which is a field somebody really owns.

    Nothing is lost by stopping there, and that is measured rather than hoped:
    sending one field under two spellings in one create is refused out loud
    (`VS403691: ... two or more updates for field with reference name ...`), so
    the pair this cannot see is the pair ADO itself will not let past.
    """
    key = _norm(name)
    row = _RESERVED_BY_SPELLING.get(key) or _READ_ONLY_BY_SPELLING.get(key)
    return _norm(row[0]) if row is not None else key


# --- the config: is this template writable at all --------------------------------

def _check_value(where, name, value, findings, warnings):
    """One template value. ADO takes a scalar; anything else configures nothing."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        return
    if not isinstance(value, str):
        findings.append("%s.%s: must be a string, number or boolean literal, "
                        "got %s - null sets nothing and a field the board "
                        "requires would still arrive empty"
                        % (where, name, type(value).__name__))
        return
    if not value.strip():
        findings.append("%s.%s: an empty string satisfies no requiredFields "
                        "rule - conventions treat empty as missing, so this "
                        "would pass validation and still be refused at push"
                        % (where, name))
        return
    if "{" in value and "}" in value:
        warnings.append("%s.%s: %r is written to the board LITERALLY - "
                        "meta.ado.fields takes no substitutions, so a "
                        "placeholder here lands on the item as those "
                        "characters" % (where, name, value))


def _check_template(wit, template, findings, warnings):
    """One work item type's template."""
    where = "meta.ado.fields.%s" % (wit,)
    if not isinstance(template, dict):
        findings.append("%s must be an object of field reference name -> "
                        "literal value, got %s" % (where, type(template).__name__))
        return
    if not template:
        warnings.append("%s is empty, so it supplies nothing - remove the key "
                        "instead if this type needs no extra fields" % (where,))
        return
    for name in sorted(template, key=str):
        if not isinstance(name, str) or not name.strip():
            findings.append("%s: every key must be a non-empty ADO field name "
                            "(reference or display), got %r" % (where, name))
            continue
        spelling = _norm(name)
        reserved = _RESERVED_BY_SPELLING.get(spelling)
        if reserved is not None:
            findings.append("%s.%s names %s, which the connector itself maps "
                            "(%s). A template cannot decide it: winning would "
                            "make commands/sync.md's mapping table a lie and "
                            "losing would make this config one"
                            % (where, name, reserved[0], reserved[2]))
            continue
        read_only = _READ_ONLY_BY_SPELLING.get(spelling)
        if read_only is not None:
            findings.append("%s.%s names %s, which ADO reports as readOnly and "
                            "will not accept through --fields. Some refuse out "
                            "loud (TF401326); System.Parent instead CREATES the "
                            "item, reports success and leaves no parent, so "
                            "attempting it would look like it worked"
                            % (where, name, read_only[0]))
            continue
        _check_value(where, name, template[name], findings, warnings)


def check_fields_config(fields):
    """(findings, warnings) for a `meta.ado.fields` block.

    Absent or null is legal and means this project supplies nothing beyond the
    connector's own mapping - which is today's behaviour exactly, and the only
    behaviour any existing manifest can have, since the key is new.
    `_manifest_ado.check_ado_meta` is the only caller in the CLI, and the panel
    reaches it through that same front door.
    """
    findings, warnings = [], []
    if fields is None:
        return findings, warnings
    if not isinstance(fields, dict):
        findings.append("meta.ado.fields must be an object keyed by work item "
                        "type name, got %s" % (type(fields).__name__,))
        return findings, warnings
    if not fields:
        warnings.append("meta.ado.fields is empty, so it supplies nothing - "
                        "remove the key rather than leaving a lever that "
                        "configures no field")
        return findings, warnings
    for wit in sorted(fields, key=str):
        if not isinstance(wit, str) or not wit.strip():
            findings.append("meta.ado.fields: every key must be a work item "
                            "type name (the same vocabulary meta.ado.types "
                            "uses), got %r" % (wit,))
            continue
        _check_template(wit, fields[wit], findings, warnings)
    return findings, warnings


def template_contradictions(ado):
    """Where `fields` and the rest of `meta.ado` disagree. Returns warnings.

    Only one shape today, and it is a SECOND MOMENT rather than a collision:
    `onComplete.remainingWork` writes Remaining Work when a task goes done, so a
    template that seeds the same field at create is correct until then and
    replaced afterwards. Refusing it would break the case the carve-out exists
    for - a board that requires Remaining Work at CREATE - so the honest answer
    is to name the overwrite at authoring time and let both keys stand.

    `onComplete.remainingWork` set to null means the field is never touched, so
    there is no second write and nothing to warn about; that is the case the
    `is None` below is for, and it is why this cannot be a truthiness test - 0
    is a real Remaining Work value and the commonest one.
    """
    out = []
    if not isinstance(ado, dict):
        return out
    fields = ado.get("fields")
    if not isinstance(fields, dict) or not fields:
        return out
    oc = ado.get("onComplete")
    if not isinstance(oc, dict):
        return out
    if "remainingWork" in oc and oc.get("remainingWork") is None:
        return out
    for wit in sorted(fields, key=str):
        template = fields.get(wit)
        if not isinstance(template, dict):
            continue
        for name in sorted(template, key=str):
            if _norm(name) in _LATE_SPELLINGS:
                out.append("meta.ado.fields.%s.%s seeds %s at create, and "
                           "meta.ado.onComplete overwrites that same field "
                           "when the task goes done. Both are legal - the "
                           "template is what gets the item past a board that "
                           "requires the field at create - but the pushed "
                           "value does not survive completion. Set "
                           "meta.ado.onComplete.remainingWork to null to keep "
                           "it." % (wit, name, LATE_WRITTEN[0]))
    return out


# --- the merge: what actually reaches the payload --------------------------------

def template_for(fields, wit):
    """The literal template for one work item type. `{}` when there is none.

    Matched EXACTLY, the way `conventions.requiredFields` matches its own keys:
    the board names its types and this file names them back, in one vocabulary.
    """
    if not isinstance(fields, dict) or not isinstance(wit, str) or not wit:
        return {}
    template = fields.get(wit)
    return template if isinstance(template, dict) else {}


def merge_template(item, fields):
    """Put this project's field template into a payload about to be sent.

    Returns `{"item": <a new payload>, "added": {...}, "skipped": {...},
    "type": <the work item type it looked up>}`. The input is never mutated -
    a caller that got a merged payload back AND had its own dict edited under
    it would have two contracts and would come to rely on the wrong one.

    `skipped` is the half that must not be silent. Validation already refuses a
    template naming anything in `RESERVED`, so a collision here means the
    payload carried a field this module's table does not list yet - a new
    mapping arriving before its row does. Dropping that quietly would hand back
    a payload the caller believes carries its template.

    Comparison is by `_canonical`, so a payload's `System.Title` and a template's
    `Title` are one field here exactly as they are on the board.
    """
    if not isinstance(item, dict):
        return {"item": item, "added": {}, "skipped": {}, "type": ""}
    wit = item.get("type") or ""
    template = template_for(fields, wit)
    existing = item.get("fields")
    existing = existing if isinstance(existing, dict) else {}

    merged = dict(item)
    merged["fields"] = dict(existing)
    taken = set(_canonical(k) for k in existing)
    added, skipped = {}, {}
    for name in sorted(template, key=str):
        if _canonical(name) in taken:
            skipped[name] = template[name]
            continue
        merged["fields"][name] = template[name]
        added[name] = template[name]
    return {"item": merged, "added": added, "skipped": skipped, "type": wit}


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_ado_fields.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__ado_fields.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
