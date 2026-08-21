#!/usr/bin/env python3
"""
`meta.ado.conventions` - what a work item must look like to belong on a board.

The connector could always write a CORRECT work item. It could not write a
CONFORMING one, and the difference only shows on a board that has a standard.
Measured 2026-08-19 against a real one (Uptimize / factory-scitara-ic-nreg-ec1):
that team's own script enforces a description skeleton, a mandatory "Done when",
acceptance criteria on stories, tags drawn from a closed vocabulary, and a
parent - none of which `/audit:sync` knew about. Its items would have hung under
a hierarchy the connector built for itself, with descriptions that skip the
skeleton and tags outside the agreed set. Mechanically right, visibly foreign.

WHY THIS IS PYTHON AND NOT PROSE IN `commands/sync.md`. The connector's writing
side is orchestrator prose driving MCP calls; no selftest reaches it, which is
precisely how the gap survived a live ADO gate. A rule that lives in prose is a
rule held in memory. Here it is a function with cases, so `conformance_violations`
can be proven red, and the only thing left unproven is whether the prose CALLS it
- which `/audit:doctor` can see after the fact, because a non-conforming item on
the board is evidence a check was skipped.

The convention is a property of the BOARD, not of the plugin: nothing here ships
a default vocabulary or a default skeleton. An absent `conventions` block means
the board has no standard to meet, and every item conforms trivially. That is the
honest reading - not "we could not check", but "there is nothing to check".

Both halves are here on purpose. `check_conventions_config` grades the block
someone wrote; `conformance_violations` grades an item against it. Splitting them
across files would put the shape and its use in two places that could disagree.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_conventions.py` - see
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

# The keys a `conventions` block may carry. Unknown keys are a did-you-mean
# WARNING and not a finding, matching `_manifest_ado`'s standing split: a wrong
# type would be misread, a wrong key configures nothing and the silence is what
# needs naming.
KNOWN_CONVENTIONS = {"requiredFields", "descriptionMustContain", "tagVocabulary",
                     "requireParent"}

# A tag is `prefix:value` or a bare word. The split is on the FIRST colon, so a
# value may contain one.
_TAG_SEP = ":"


# --- the config: is this block writable at all -----------------------------------

def _check_required_fields(block, findings):
    """`requiredFields`: {work item type: [ADO field reference name, ...]}."""
    if not isinstance(block, dict):
        findings.append("meta.ado.conventions.requiredFields must be an object "
                        "keyed by work item type, got %s"
                        % (type(block).__name__,))
        return
    for wit, fields in sorted(block.items()):
        where = "meta.ado.conventions.requiredFields.%s" % (wit,)
        if not isinstance(fields, list):
            findings.append("%s must be a list of field reference names, got %s"
                            % (where, type(fields).__name__))
            continue
        bad = [x for x in fields if not isinstance(x, str) or not x.strip()]
        if bad:
            findings.append("%s: every entry must be a non-empty field reference "
                            "name (%d bad: %r)" % (where, len(bad), bad[:3]))


def _check_description_markers(block, findings):
    """`descriptionMustContain`: {work item type: [literal marker, ...]}."""
    if not isinstance(block, dict):
        findings.append("meta.ado.conventions.descriptionMustContain must be an "
                        "object keyed by work item type, got %s"
                        % (type(block).__name__,))
        return
    for wit, markers in sorted(block.items()):
        where = "meta.ado.conventions.descriptionMustContain.%s" % (wit,)
        if not isinstance(markers, list):
            findings.append("%s must be a list of literal markers, got %s"
                            % (where, type(markers).__name__))
            continue
        bad = [x for x in markers if not isinstance(x, str) or not x.strip()]
        if bad:
            findings.append("%s: every marker must be a non-empty string "
                            "(%d bad: %r)" % (where, len(bad), bad[:3]))


def _check_tag_vocabulary(block, findings, warnings):
    """`tagVocabulary`: {prefix: [allowed value, ...]}, plus `*` for bare tags.

    `*` is the escape hatch and it is spelled rather than implied: a board that
    allows free-form tags says so, and a board that does not gets a finding on
    the first bare tag instead of silently accepting anything without a colon.
    """
    if not isinstance(block, dict):
        findings.append("meta.ado.conventions.tagVocabulary must be an object "
                        "keyed by tag prefix, got %s" % (type(block).__name__,))
        return
    if not block:
        warnings.append("meta.ado.conventions.tagVocabulary is empty, which "
                        "forbids every tag - remove the key instead if the board "
                        "has no tag standard")
    for prefix, values in sorted(block.items()):
        where = "meta.ado.conventions.tagVocabulary.%s" % (prefix,)
        if not isinstance(values, list):
            findings.append("%s must be a list of allowed values, got %s"
                            % (where, type(values).__name__))
            continue
        bad = [x for x in values if not isinstance(x, str) or not x.strip()]
        if bad:
            findings.append("%s: every allowed value must be a non-empty string "
                            "(%d bad: %r)" % (where, len(bad), bad[:3]))


def check_conventions_config(conventions):
    """(findings, warnings) for a `meta.ado.conventions` block.

    Absent or null is legal and means the board has no standard - see the module
    docstring. `_manifest_ado.check_ado_meta` is the only caller in the CLI, and
    the panel reaches it through the same front door.
    """
    findings, warnings = [], []
    if conventions is None:
        return findings, warnings
    if not isinstance(conventions, dict):
        findings.append("meta.ado.conventions must be an object or null, got %s"
                        % (type(conventions).__name__,))
        return findings, warnings

    unknown = sorted(set(conventions) - KNOWN_CONVENTIONS)
    if unknown:
        warnings.append("meta.ado.conventions: unknown key(s) %r configure "
                        "nothing - known keys are %r"
                        % (unknown, sorted(KNOWN_CONVENTIONS)))

    if "requiredFields" in conventions:
        _check_required_fields(conventions["requiredFields"], findings)
    if "descriptionMustContain" in conventions:
        _check_description_markers(conventions["descriptionMustContain"], findings)
    if "tagVocabulary" in conventions:
        _check_tag_vocabulary(conventions["tagVocabulary"], findings, warnings)
    if "requireParent" in conventions:
        if not isinstance(conventions["requireParent"], bool):
            findings.append("meta.ado.conventions.requireParent must be true or "
                            "false, got %s"
                            % (type(conventions["requireParent"]).__name__,))
    return findings, warnings


# --- the item: does this one belong on the board ---------------------------------

def split_tags(raw):
    """ADO's `System.Tags` is one string; this is the list it means.

    Separator is `;` and surrounding whitespace is not significant, which is what
    the field's own round-trip does. An empty string is no tags, not one blank
    tag - the distinction matters because `requireParent`-style emptiness checks
    read this list's length.
    """
    if not raw:
        return []
    return [t.strip() for t in str(raw).split(";") if t.strip()]


def _tag_violations(tags, vocabulary):
    """Which tags this board's vocabulary does not admit."""
    out = []
    free_form = "*" in vocabulary
    for tag in tags:
        if _TAG_SEP in tag:
            prefix, value = tag.split(_TAG_SEP, 1)
            prefix, value = prefix.strip(), value.strip()
            if prefix not in vocabulary:
                out.append("tag %r uses prefix %r, which is not in the "
                           "vocabulary %r" % (tag, prefix, sorted(vocabulary)))
            elif value not in vocabulary[prefix]:
                out.append("tag %r is not an allowed value for %r - allowed: %r"
                           % (tag, prefix, sorted(vocabulary[prefix])))
        elif not free_form:
            out.append("tag %r has no vocabulary prefix, and this board does not "
                       "allow free-form tags (add \"*\" to tagVocabulary if it "
                       "should)" % (tag,))
    return out


# The keys only a FETCHED work item carries. `az boards work-item show` and the
# REST API both return these; a payload the connector is about to send has no
# revision, no url and no links, because it does not exist yet.
_FETCHED_ONLY = ("rev", "url", "_links", "relations")


def rest_payload_reason(item):
    """Why this looks like a work item READ BACK, not one about to be sent.

    `None` when the payload is the shape this module grades. Otherwise a
    sentence naming what gave it away, for a caller to print before refusing.

    This exists because the two shapes OVERLAP, which is worse than being
    unrelated. `az boards work-item show` output carries `fields`, so the tag
    rules really do read the tags - but `type` and `parent` live somewhere else
    in that shape, so `requireParent` fires on an item that HAS a parent and
    `requiredFields` grades a work item type it never learned. The result was a
    confident "DOES NOT CONFORM: do NOT create this item" about a correct,
    long-existing item. A checker whose every message is precise, aimed at the
    wrong shape, is worse than one that says nothing.

    The tell is deliberately structural rather than a guess: the payload must
    look fetched (a revision, a url, links, relations - none of which a
    not-yet-created item can have) AND be missing the `type` this module needs.
    An item that merely omits `type` is left alone; that is a conformance
    question, not a shape one.
    """
    if not isinstance(item, dict):
        return None
    if item.get("type"):
        return None
    if not isinstance(item.get("fields"), dict):
        return None
    seen = [k for k in _FETCHED_ONLY if k in item]
    if not seen:
        return None
    return ("this payload carries %s and no top-level `type`, so it looks like "
            "a work item read back from ADO rather than one about to be sent. "
            "The expected shape is {\"type\": \"Task\", \"fields\": {...}, "
            "\"parent\": 123} - `type` and `parent` sit beside `fields`, not "
            "inside it. Graded as-is, `requireParent` would fire on an item "
            "that HAS a parent." % (", ".join("`" + k + "`" for k in seen),))


def provenance_tag_violations(tag, conventions):
    """Would this board's vocabulary refuse the tag the connector itself writes?

    `[]` when it is admitted, when there is no vocabulary, or when there is no
    tag. Otherwise the same sentences `conformance_violations` would produce -
    because it is the SAME function underneath. That is the whole point of this
    door existing: `_manifest_ado` needs to ask the question at authoring time,
    and a second copy of the tag rule there would be a second answer the first
    time either one learned a prefix.

    F-P-18: `meta.ado.tag` defaults to `audit-plugin`, which has no prefix, so a
    board whose `tagVocabulary` admits only prefixed tags refuses every item the
    connector creates - and the manifest still validated clean, because each
    block was graded alone. Nothing was wrong with either block; they disagreed.
    """
    if not isinstance(conventions, dict) or not conventions:
        return []
    vocabulary = conventions.get("tagVocabulary")
    if not isinstance(vocabulary, dict) or not vocabulary:
        return []
    if not isinstance(tag, str) or not tag.strip():
        return []
    return _tag_violations(split_tags(tag), vocabulary)


def conformance_violations(item, conventions):
    """What stops `item` from belonging on this board. `[]` means it conforms.

    `item` is the normalised shape the connector is about to send:

        {"type": "Task",
         "fields": {"System.Title": "...", "System.Description": "...",
                    "System.Tags": "type:refactor; supplier:databridge"},
         "parent": 103205}

    Every rule is scoped BY TYPE where the board scopes it by type, because a
    story and a task do not owe the same fields - and a checker that demanded
    acceptance criteria on a task would be refused so often it would be switched
    off, which is the failure mode a conformance check has to avoid.
    """
    if not isinstance(conventions, dict) or not conventions:
        return []
    if not isinstance(item, dict):
        return ["item must be an object, got %s" % (type(item).__name__,)]

    wit = item.get("type") or ""
    fields = item.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    out = []

    required = conventions.get("requiredFields") or {}
    if isinstance(required, dict):
        for name in (required.get(wit) or []):
            value = fields.get(name)
            if value is None or not str(value).strip():
                out.append("%s requires field %s, which is missing or empty"
                           % (wit or "item", name))

    markers = conventions.get("descriptionMustContain") or {}
    if isinstance(markers, dict):
        description = str(fields.get("System.Description") or "")
        for marker in (markers.get(wit) or []):
            if marker.lower() not in description.lower():
                out.append("%s description must contain %r - the board's "
                           "skeleton is not optional" % (wit or "item", marker))

    vocabulary = conventions.get("tagVocabulary")
    if isinstance(vocabulary, dict):
        out.extend(_tag_violations(split_tags(fields.get("System.Tags")),
                                   vocabulary))

    if conventions.get("requireParent") is True:
        parent = item.get("parent")
        # 0 is not a work item id, and neither is "". Anything else that is
        # present counts - the connector may carry the id as an int or a string
        # depending on which side handed it over.
        if parent is None or str(parent).strip() in ("", "0"):
            out.append("%s must hang under a parent work item, and this one "
                       "carries none - a board with a backlog wants audit work "
                       "INSIDE it, not beside it" % (wit or "item",))
    return out


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
        print("_ado_conventions.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__ado_conventions.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
