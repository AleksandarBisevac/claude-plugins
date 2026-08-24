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
  check-ado-item.py <manifest> --fetched <fetched.json>   # status step 5
  check-ado-item.py <manifest> --fetched - --json

`--item` is the normalised shape the connector is about to CREATE:

  {"type": "Task",
   "fields": {"System.Title": "...", "System.Description": "...",
              "System.Tags": "type:refactor; supplier:databridge"},
   "parent": 103205}

`--fetched` IS THE OTHER SHAPE, AND IT IS A DIFFERENT QUESTION (F106). It takes
the item list `fetch-ado-items.py --out` writes - rows of `{id, fields}`, with
the work item type and the parent INSIDE `fields` - and asks whether the items
already ON the board still conform. That payload used to be fed to `--item`,
where `requireParent` read a top-level `parent` the shape does not have and
refused an item that had one, while the type-scoped rules silently checked
nothing. So `--item` now refuses that shape outright and this flag translates it
(`_ado_conventions.as_gradable_item`) instead of asking the caller to remember
which key holds the parent.

Two things this path deliberately does NOT do. It does not merge
`meta.ado.fields`: that template is what a CREATE must send, and merging it into
an item already on the board would supply a field the board does not have and
grade a fiction. And it does not say "do NOT create this item" - nobody is
creating these; a violation here is a report about a card that is already
sitting on somebody's board.

A `NOTE:` LINE IS NOT A REFUSAL, and F120 is why there is one. `requireParent`
grades the parent the connector RESOLVED, and push resolves none for a bug -
it creates that card with no parent link and names no third kind to hang - so
the rule was refusing every bug create on any board that set it. It is scoped
by work item type now, read from `meta.ado.types`, and the exemption is PRINTED
rather than applied in silence: a board asking for a parent on every card is
asking for something this connector cannot supply, which is a sentence its
operator is entitled to. It moves neither the exit code nor `conforms`;
`--json` carries it as `parentRuleExemption`.

Only `meta.ado.conventions` and `meta.ado.types` are read, and both live in the
manifest INDEX, so a sharded manifest needs no shard walk here.

Exit codes: 0 = conforms (or the board has no standard) - 1 = violations -
2 = usage error or unreadable input. On `--fetched` the WORST outcome across the
rows wins, and a row whose work item type the payload does not carry is a 2 for
the same reason it is on `--item`: it was not graded at all, and a report that
counted it as conforming would be the silent pass this command exists to stop.
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
import _ado_parent as _parent  # noqa: E402  (which kinds a push leaves unparented)

USAGE = ("usage: check-ado-item.py <manifest> --item <file.json|-> [--json]\n"
         "       check-ado-item.py <manifest> --fetched <fetched.json|-> "
         "[--json]\n"
         "       (--item is a create payload, --fetched is the item list "
         "fetch-ado-items.py --out writes; they are different shapes and "
         "different verdicts, so exactly one is required)\n")


def ado_of(manifest):
    """`meta.ado`, or None when this manifest has no connector configured.

    Tolerant on the way down on purpose: a manifest whose `meta` or `ado` is the
    wrong type is `check_ado_meta`'s finding to report, not this command's to
    crash on. Here the only question is what there is to apply.

    The three readers below all start here rather than each digging their own
    way down, which is what stopped being a detail when a third one arrived.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    ado = meta.get("ado") if isinstance(meta, dict) else None
    return ado if isinstance(ado, dict) else None


def conventions_of(manifest):
    """`meta.ado.conventions`, or None when the board has no standard."""
    ado = ado_of(manifest)
    return ado.get("conventions") if ado else None


def field_template_of(manifest):
    """`meta.ado.fields`, or None when this project supplies nothing extra."""
    ado = ado_of(manifest)
    return ado.get("fields") if ado else None


def unparented_of(manifest):
    """The work item types push CREATES without a parent link (F120).

    Handed to `_ado_conventions` rather than read there, because that module
    grades a `conventions` block and this command is the one holding the whole
    of `meta.ado`. A manifest with no connector block still gets the connector's
    default answer: `meta.ado` absent does not mean push would suddenly start
    parenting bugs, and an empty tuple here would put the F120 refusal back for
    exactly the manifests that configured nothing.

    ASKED OF `_ado_parent` because that is where the bug type name is derived -
    it reads every other name in `meta.ado.types` too. It answered from
    `_ado_conventions` for one release, next to a second derivation in
    `_ado_parent` that disagreed with it on a blank and on a padded name.
    """
    return _parent.unparented_types(ado_of(manifest))


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


def flag_value(argv, flag):
    """The value after `flag`, or None when it is absent, last, or another flag.

    `-` IS A VALUE here - it names stdin - which is why this cannot just test for
    a leading dash. `--item --json` reading the flag as a filename produced a
    read error naming `--json` as a missing file, which is a true sentence about
    the wrong problem.
    """
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if len(argv) <= idx + 1:
        return None
    value = argv[idx + 1]
    return None if value.startswith("--") else value


def read_json(path, label):
    """(payload, error) from a file or from stdin when `path` is `-`.

    `label` names the input in the error, because "cannot read/parse item" and
    "cannot read/parse fetched payload" send a reader to different files.
    """
    try:
        if path == "-":
            return json.load(sys.stdin), None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as exc:
        return None, "cannot read/parse %s %s: %s" % (label, path, exc)


def no_standard_line(manifest_path):
    """The one sentence both paths print when the board has no standard.

    Named rather than silent, and spelled ONCE: "nothing to check" and
    "checked, clean" are different answers, and a caller that cannot tell them
    apart will read an unconfigured board as a conforming one. Two copies of
    this sentence would be two chances for one of them to become the clean one.
    """
    return ("OK: %s declares no meta.ado.conventions - this board has no "
            "standard to meet, so nothing was checked." % (manifest_path,))


# --- --fetched: what is already on the board -------------------------------------

def fetched_rows(payload):
    """(rows, error) for a `--fetched` input. Rows are `{id, fields}` as written.

    The PARTIAL payload is refused by name. `fetch-ado-items.py --json` carries
    an `items` list too, but it also carries `failures`, and that command says of
    itself that a payload missing the chunk that timed out "reads downstream as a
    clean board for exactly those items". Grading it would report a whole board
    from a fetch that lost part of it, so this asks for the `--out` file, which
    is written only from what came back.
    """
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return None, ("this looks like `fetch-ado-items.py --json`, whose "
                      "payload can be PARTIAL - it carries `failures` and a "
                      "chunk that timed out is simply absent from `items`. Pass "
                      "the file written by `--out` instead, which is the item "
                      "list alone, or a lost chunk reads here as a clean board")
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        return [payload], None
    return None, ("the --fetched payload must be the item list "
                  "`fetch-ado-items.py --out` writes, or one such row, got %s"
                  % (type(payload).__name__,))


def _not_gradeable_reason(row):
    """Why THIS row cannot be graded, said in the fetched payload's own terms.

    The DECISION is not made here - `rest_payload_reason` makes it, once, for
    both paths. Only the sentence differs, and it has to: the create path is
    told "your payload has no top-level `type`", which on this path would send a
    reader looking for a key the board never puts there. The thing actually
    missing from a fetched row is the SELECT field, so that is what this names.
    """
    if not isinstance(row, dict):
        return ("this entry is not a work item row (%s) - a row is "
                "{\"id\": ..., \"fields\": {...}}" % (type(row).__name__,))
    return ("this row carries no `System.WorkItemType`, so the board's "
            "type-scoped rules cannot be looked up for it - `_ado_fetch.FIELDS` "
            "is the SELECT list that keeps that field, and a narrower query "
            "comes back without it")


def grade_fetched(rows, conventions, unparented=None):
    """One entry per fetched row: graded, or NAMED as not gradeable.

    A row this gate cannot read is a ROW, never a skip. Dropping it would leave a
    shorter table reading as a complete one - the same defect
    `_ado_fetch.missing_ids` exists to prevent one layer up - and counting it as
    conforming would be the silent pass F106 is half made of.

    `exemption` rides along for the same reason it does on the create path: a
    rule that narrowed has to say it narrowed. It is NOT a violation and does
    not move the tally or the exit code - a bug card already on the board is
    neither refused nor a defect, it is a card this connector could not have
    parented.
    """
    out = []
    for row in (rows or []):
        item = _conv.as_gradable_item(row)
        refused = _conv.rest_payload_reason(item) is not None
        fields = item.get("fields") or {}
        out.append({"id": item.get("id"),
                    "type": item.get("type"),
                    "title": fields.get("System.Title"),
                    "graded": not refused,
                    "reason": _not_gradeable_reason(row) if refused else None,
                    "exemption": (None if refused
                                  else _conv.parent_rule_exemption(
                                      item, conventions, unparented)),
                    "violations": ([] if refused
                                   else _conv.conformance_violations(
                                       item, conventions, unparented))})
    return out


def fetched_tally(graded):
    """The counts the closing line and the exit code are both read from.

    One derivation, because a printed count and an exit code that disagree is
    the shape where a reader believes the friendlier of the two.
    """
    ready = [row for row in graded if row["graded"]]
    return {"total": len(graded),
            "graded": len(ready),
            "notGradeable": len(graded) - len(ready),
            "conforming": len([r for r in ready if not r["violations"]]),
            "violating": len([r for r in ready if r["violations"]])}


def fetched_exit(tally):
    """Worst outcome wins, and the order is deliberate.

    A row nothing could grade outranks a row that was graded and refused: the
    second is an answer, the first is a missing basis, and a command that
    returned 1 for it would let a caller believe every row had been read.
    """
    if tally["notGradeable"]:
        return 2
    if tally["violating"]:
        return 1
    return 0


def _row_label(row):
    """`#<id> <type> "<title>"`, with an absent part LEFT OUT rather than faked.

    A row with no title is a row whose SELECT did not ask for one, and a
    stand-in would read as the board's own answer to a question nobody put.
    """
    parts = ["#%s" % (row["id"],) if row["id"] is not None else "#?"]
    if row["type"]:
        parts.append(str(row["type"]))
    if row["title"]:
        parts.append("\"%s\"" % (row["title"],))
    return " ".join(parts)


def fetched_lines(graded, tally, path):
    """The per-row report and the closing count, printed EVEN AT ZERO.

    An empty payload says so in words. "no linked item was checked" and "every
    linked item conforms" are the two zeroes this whole command exists to keep
    apart, and a closing line that appears only when there is something to count
    cannot be told from a count nobody computed.
    """
    out = []
    for row in graded:
        label = _row_label(row)
        if not row["graded"]:
            out.append("%s: NOT GRADED - %s" % (label, row["reason"]))
            continue
        if row["violations"]:
            out.append("%s: %d violation(s)" % (label, len(row["violations"])))
            for line in row["violations"]:
                out.append("  FINDING: " + line)
        else:
            out.append("%s: conforms" % (label,))
        # UNDER the verdict and indented like a FINDING, because it qualifies
        # that verdict rather than replacing it: this row conforms, and one of
        # the board's rules was not among the ones it was measured against.
        if row.get("exemption"):
            out.append("  NOTE: " + row["exemption"])
    if not graded:
        out.append("conventions: no linked item(s) in %s - nothing was checked, "
                   "which is not the same answer as nothing being wrong" % (path,))
        return out
    out.append("conventions: %d of %d linked item(s) conform"
               % (tally["conforming"], tally["total"]))
    if tally["notGradeable"]:
        out.append("NOT GRADED: %d of %d - those rows were not checked at all, "
                   "so they are neither conforming nor refused; the line above "
                   "each one says what was missing"
                   % (tally["notGradeable"], tally["total"]))
    return out


def run_fetched(manifest_path, manifest, path, as_json):
    """`--fetched`: grade the items already ON the board, one row at a time.

    NO TEMPLATE MERGE HERE, deliberately. `meta.ado.fields` is what a CREATE must
    send; merging it into an item already on the board would supply a field the
    board does not have and grade a fiction that conforms.
    """
    payload, err = read_json(path, "fetched payload")
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2
    rows, shape_err = fetched_rows(payload)
    if shape_err:
        sys.stderr.write("ERROR: %s\n" % (shape_err,))
        return 2

    conventions = conventions_of(manifest)
    if conventions is None or not conventions:
        # Asked BEFORE grading, because with no conventions every row would come
        # back with an empty violation list and print as "conforms" - the two
        # zeroes collapsed into the friendlier one.
        if as_json:
            print(json.dumps({"conforms": True, "hasStandard": False,
                              "items": [], "conforming": 0, "graded": 0,
                              "notGradeable": 0, "total": len(rows)},
                             indent=2, sort_keys=True))
            return 0
        print(no_standard_line(manifest_path))
        return 0

    graded = grade_fetched(rows, conventions, unparented_of(manifest))
    tally = fetched_tally(graded)
    code = fetched_exit(tally)
    if as_json:
        print(json.dumps({"conforms": code == 0, "hasStandard": True,
                          "items": graded, "conforming": tally["conforming"],
                          "graded": tally["graded"],
                          "notGradeable": tally["notGradeable"],
                          "total": tally["total"]},
                         indent=2, sort_keys=True))
        return code
    for line in fetched_lines(graded, tally, path):
        print(line)
    return code


# --- --item: what is about to be created -----------------------------------------

def run_item(manifest_path, manifest, path, as_json):
    """`--item`: the gate a CREATE goes through before it happens."""
    item, err = read_json(path, "item")
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2

    # A LIST is the other flag's input, and it used to come back as
    # "DOES NOT CONFORM: 1 violation(s) - do NOT create this item" via
    # `conformance_violations`' "item must be an object" - a conformance verdict
    # about a shape mistake, which is F106 in miniature. Exit 2 and say which
    # flag wants it.
    if not isinstance(item, dict):
        sys.stderr.write("ERROR: an --item payload is ONE create object; this is "
                         "%s. The item list `fetch-ado-items.py --out` writes "
                         "goes to --fetched, which grades every row in it.\n"
                         % (type(item).__name__,))
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
    unparented = unparented_of(manifest)
    violations = _conv.conformance_violations(merge["item"], conventions,
                                              unparented)
    exemption = _conv.parent_rule_exemption(merge["item"], conventions,
                                            unparented)

    if as_json:
        print(json.dumps({"conforms": not violations,
                          "hasStandard": bool(conventions),
                          "violations": violations,
                          # NOT a violation and never counted as one: it says
                          # which rule did not apply to this kind of item, so a
                          # script reading `conforms` alone still gets the right
                          # answer and one reading this gets the whole of it.
                          "parentRuleExemption": exemption,
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
        print(no_standard_line(manifest_path))
        return 0
    # BEFORE the verdict on this path, unlike `--fetched`, because here the
    # verdict is an instruction: "create it" read without knowing a rule was
    # skipped is the create this gate exists to think twice about.
    if exemption:
        print("NOTE: " + exemption)
    if violations:
        for line in violations:
            print("FINDING: " + line)
        print("\nDOES NOT CONFORM: %d violation(s) - do NOT create this item."
              % (len(violations),))
        return 1
    print("OK: the item conforms to %s's meta.ado.conventions."
          % (manifest_path,))
    return 0


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    wants_item = "--item" in argv
    wants_fetched = "--fetched" in argv
    if wants_item == wants_fetched:
        # Both, or neither. Refusing to guess IS the subject of this file: the
        # two flags name two shapes and two verdicts, and picking one for a
        # caller who named both is how the wrong shape got graded to begin with.
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]
    path = flag_value(argv, "--item" if wants_item else "--fetched")
    if not path:
        sys.stderr.write(USAGE)
        return 2
    as_json = "--json" in argv

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2

    if wants_fetched:
        return run_fetched(manifest_path, manifest, path, as_json)
    return run_item(manifest_path, manifest, path, as_json)


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
