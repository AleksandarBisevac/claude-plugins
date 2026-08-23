#!/usr/bin/env python3
"""
The gate `/audit:sync push` runs an item through before it creates it.

`_ado_conventions` holds the rule; this is the door the orchestrator knocks on.
It exists as a real command rather than a `python3 -c` one-liner for two
reasons, and the second is not style: a one-liner that names a source path is
exactly the shape `guard-secrets-read` refuses (F20/F22), so the check would be
blocked on the machines that most need it.

WHY A GATE AND NOT AN ADVISORY. `SECURITY.md` splits these: advisory paths fail
open, guards fail loud. An item that does not conform is not a warning to read
later - it is a work item that would land on someone's board looking foreign,
and once created it stays. So a violation is exit 1 and the caller stops.

  FINDING  - the item does not belong on this board (exit 1).

WHAT COMES BACK IS THE PAYLOAD TO SEND. `meta.ado.fields` is merged into the
item BEFORE it is graded, because a gate that can only refuse is useless on a
board whose Task owes fields the connector never learned to write. So this
command prints what it added and `--json` carries the merged `payload`: send
THAT, not the item you wrote, or the fields the gate just counted as present
will not be on the created item.

Usage:
  check-ado-item.py <manifest> --item <file.json>
  check-ado-item.py <manifest> --item -            # payload on stdin
  check-ado-item.py <manifest> --item f.json --json

The payload is the normalised shape the connector is about to send:

  {"type": "Task",
   "fields": {"System.Title": "...", "System.Description": "...",
              "System.Tags": "type:refactor; supplier:databridge"},
   "parent": 103205}

Only `meta.ado.conventions` is read, and it lives in the manifest INDEX, so a
sharded manifest needs no shard walk here.

Exit codes: 0 = conforms (or the board has no standard) - 1 = violations -
2 = usage error or unreadable input.
"""
import json
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

import _ado_conventions as _conv  # noqa: E402  (the rule this command enforces)
import _ado_fields as _fields  # noqa: E402  (the template merged in before it)

USAGE = ("usage: check-ado-item.py <manifest> --item <file.json|-> [--json]\n")


def conventions_of(manifest):
    """`meta.ado.conventions`, or None when the board has no standard.

    Tolerant on the way down on purpose: a manifest whose `meta` or `ado` is the
    wrong type is `check_ado_meta`'s finding to report, not this command's to
    crash on. Here the only question is whether there is a standard to apply.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado.get("conventions") if isinstance(ado, dict) else None


def field_template_of(manifest):
    """`meta.ado.fields`, or None when this project supplies nothing extra.

    Same tolerance as `conventions_of` and for the same reason: a manifest whose
    `meta` or `ado` is the wrong type is `check_ado_meta`'s finding to report.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado.get("fields") if isinstance(ado, dict) else None


def _report_merge(result, has_block):
    """The lines that make the merge visible. `[]` when there was no block.

    A merge nobody printed is a payload the caller does not know it has to send,
    and a skip nobody printed is a template the caller believes was applied. An
    ABSENT block prints nothing at all, which is what keeps "this key is not
    set" byte-identical to the behaviour before the key existed.
    """
    if not has_block:
        return []
    wit = result["type"] or "item"
    out = []
    if result["added"]:
        out.append("MERGED: %d field(s) from meta.ado.fields.%s - send these "
                   "with the create:" % (len(result["added"]), wit))
        for name in sorted(result["added"]):
            out.append("  %s=%r" % (name, result["added"][name]))
    elif not result["skipped"]:
        out.append("MERGED: meta.ado.fields declares no template for %s, so "
                   "the payload is unchanged." % (wit,))
    for name in sorted(result["skipped"]):
        out.append("WARNING: meta.ado.fields.%s.%s was NOT merged - the "
                   "payload already carries that field, and the connector's "
                   "own value wins." % (wit, name))
    return out


def main(argv):
    if "--item" not in argv or not argv or argv[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]
    item_path = argv[argv.index("--item") + 1] if len(argv) > argv.index("--item") + 1 else None
    if not item_path:
        sys.stderr.write(USAGE)
        return 2
    as_json = "--json" in argv

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2

    try:
        if item_path == "-":
            item = json.load(sys.stdin)
        else:
            with open(item_path, "r", encoding="utf-8") as fh:
                item = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse item %s: %s\n" % (item_path, exc))
        return 2

    # Shape before substance. Exit 2, never 1: a 1 means "this item does not
    # belong on the board", and saying that about a payload we could not read
    # properly is the confident-wrong-answer this guard exists to stop.
    reason = _conv.rest_payload_reason(item)
    if reason:
        sys.stderr.write("ERROR: %s\n" % (reason,))
        return 2

    # The template is merged BEFORE grading, and a malformed one is exit 2
    # rather than 1: a 1 says "this item does not belong on the board", and a
    # config we refused to read is not the item's fault. Without this the
    # refusals `_ado_fields` exists for - a connector-mapped field, a readOnly
    # one - would be validation findings nobody on this path ever ran.
    template = field_template_of(manifest)
    tf, _ = _fields.check_fields_config(template)
    if tf:
        for line in tf:
            sys.stderr.write("ERROR: %s\n" % (line,))
        sys.stderr.write("ERROR: meta.ado.fields in %s cannot be applied; fix "
                         "it (validate-manifest.py reports the same findings) "
                         "and re-run.\n" % (manifest_path,))
        return 2
    merge = _fields.merge_template(item, template)
    has_block = template is not None

    conventions = conventions_of(manifest)
    violations = _conv.conformance_violations(merge["item"], conventions)

    if as_json:
        print(json.dumps({"conforms": not violations,
                          "hasStandard": bool(conventions),
                          "violations": violations,
                          # The payload to SEND. With no template it is the item
                          # that came in, unchanged - which is the claim the key
                          # being absent makes, in a form a script can check.
                          "payload": merge["item"],
                          "fieldsAdded": merge["added"],
                          "fieldsSkipped": merge["skipped"]},
                         indent=2, sort_keys=True))
        return 1 if violations else 0

    for line in _report_merge(merge, has_block):
        print(line)

    if conventions is None or not conventions:
        # Named rather than silent: "nothing to check" and "checked, clean" are
        # different answers, and a caller that cannot tell them apart will read
        # an unconfigured board as a conforming one.
        print("OK: %s declares no meta.ado.conventions - this board has no "
              "standard to meet, so nothing was checked." % (manifest_path,))
        return 0
    if violations:
        for line in violations:
            print("FINDING: " + line)
        print("\nDOES NOT CONFORM: %d violation(s) - do NOT create this item."
              % (len(violations),))
        return 1
    print("OK: the item conforms to %s's meta.ado.conventions."
          % (manifest_path,))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("check-ado-item.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_check_ado_item.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
