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

SHAPE BEFORE SUBSTANCE, and that is the third thing here. There are two payloads
in play - one about to be created, one read back off the board - they overlap
enough to grade each other's rules wrongly, and only the first can be graded as
written. `rest_payload_reason` says when a caller has the wrong one and
`as_gradable_item` converts the other, so the answer to "can this be graded" is
a function with cases rather than a paragraph a caller has to remember.

AND ONE RULE IS SCOPED BY KIND, WHICH IS F120. `requireParent` reads the parent
the connector RESOLVED for an item, and push resolves one for a phase (and, with
`phaseWorkItems` off, a task) and for no third kind: a bug card is created with
no parent link at all, which `_ado_parent.resolve(kind="bug")` already says from
the other side by refusing to let `meta.ado.parentWorkItem` reach a bug. So the
rule was refusing every bug create on any board that set it, at create time, for
a parent nothing was ever going to supply. It is scoped now - and the exemption
is SPOKEN rather than silent, because a board that really does want a parent on
every card is asking for something this connector cannot give it, and that is a
sentence to print, not a check to skip. `parent_rule_exemption` is that door;
`conformance_violations` asks it too, so the reason and the skip cannot drift.

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

# The vocabulary key that covers bare, unprefixed tags. Spelled once because two
# functions read it: the config half grades its list, the item half applies it.
_TAG_ANY = "*"


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

    Its list is graded like any other key's because it is APPLIED like any other
    key's - see `_tag_violations`. The one thing only this key can get wrong is
    an entry carrying a colon: a tag with a prefix is graded against that
    prefix, so such an entry is unreachable, and an unreachable entry
    configures nothing. That is the module's standing split - a wrong type is a
    finding because it would be misread, a setting that does nothing is a
    warning because the silence is what needs naming.
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
        if prefix == _TAG_ANY:
            unreachable = [x for x in values
                           if isinstance(x, str) and _TAG_SEP in x]
            if unreachable:
                warnings.append("%s: %r can never match - an entry carrying a "
                                "colon is a PREFIXED tag, and a prefixed tag is "
                                "graded against its own prefix and never "
                                "reaches \"*\", which lists what a BARE tag may "
                                "be" % (where, unreachable))


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
    """Which tags this board's vocabulary does not admit.

    `*` IS A KEY LIKE ANY OTHER AND ITS LIST RESTRICTS. `{"*": ["FE", "BE"]}`
    admits those bare tags and refuses the rest, exactly as `{"supplier": [...]}`
    does for `supplier:...`. Only the key's PRESENCE used to be read, so that
    board got no restriction and no warning while its entries were validated as
    strings nothing ever consulted - the code did not do what its own schema
    said, and a vocabulary author had no way to find out.

    THE EMPTY LIST IS THE ONE ASYMMETRY, and it is deliberate rather than an
    oversight. `{"*": []}` admits any bare tag, while `{"supplier": []}` admits
    no `supplier:` value. Two reasons, and the second is the load-bearing one.
    It reads correctly: a wildcard with nothing narrowing it is still a
    wildcard, and a restriction is something you opt into by LISTING. And it is
    the spelling already published - the schema, `docs/ado-connector.md` and
    this repo's own example all write `{"*": []}` for a free-form board, so
    reading it as "forbids every bare tag" would change the meaning of a
    manifest somebody already wrote, which is a major release rather than a fix.

    Neither branch second-guesses a malformed list. `{"supplier": "databridge"}`
    is already a config FINDING, and inventing a grading rule for it here would
    be a second answer to a question `check_conventions_config` has answered.
    """
    out = []
    admits_bare = _TAG_ANY in vocabulary
    bare_allowed = vocabulary.get(_TAG_ANY)
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
        elif not admits_bare:
            out.append("tag %r has no vocabulary prefix, and this board does not "
                       "allow free-form tags (add \"*\" to tagVocabulary if it "
                       "should)" % (tag,))
        elif bare_allowed and tag not in bare_allowed:
            # A DIFFERENT sentence from the one above, for the same reason a bad
            # value under a known prefix is: `*` is already there, so repeating
            # the opt-in advice would send the reader in a circle.
            out.append("tag %r is not an allowed bare tag - \"*\" lists what an "
                       "unprefixed tag may be, and allows: %r"
                       % (tag, sorted(bare_allowed)))
    return out


# The keys only a FETCHED work item carries. NOT THE TELL any more - see
# `rest_payload_reason` - but still worth NAMING when they are there, because
# "you handed me a work item read back from the board" is a sentence a caller can
# act on, where "your payload has no type" leaves it guessing which end is wrong.
_FETCHED_ONLY = ("rev", "url", "_links", "relations")


def rest_payload_reason(item):
    """Why this payload cannot be graded as an item about to be sent.

    `None` when the payload is the shape this module grades. Otherwise a
    sentence naming what gave it away, for a caller to print before refusing.

    This exists because the two shapes OVERLAP, which is worse than being
    unrelated. A fetched work item carries `fields`, so the tag rules really do
    read its tags - but `type` and `parent` live somewhere else in that shape, so
    `requireParent` fires on an item that HAS a parent while `requiredFields`
    and `descriptionMustContain` grade a work item type they never learned. The
    result was a confident "DOES NOT CONFORM: do NOT create this item" about a
    correct, long-existing item. A checker whose every message is precise, aimed
    at the wrong shape, is worse than one that says nothing.

    THE TELL IS THE ABSENT `type`, NOT THE PRESENT DECORATION, AND THAT IS F106.
    This guard used to require one of `_FETCHED_ONLY` to be present. That read
    as structural and was not: `_ado_fetch.as_items()` - this plugin's OWN batch
    producer, and what `/audit:sync status` feeds the gate - emits
    `{"id": ..., "fields": {...}}` and strips all four markers, so the guard
    could not see the one shape it was built for and the item that HAD a parent
    was refused for carrying none. Teaching that producer to keep a marker would
    fix that producer; the next one to trim a field - a `jq` over
    `az boards work-item show`, a hand-assembled row, a narrower SELECT - brings
    the bug straight back, because a list of decorations that happen to be
    present is a list and not a rule.

    Absence of `type` cannot be defeated that way, because `type` is not
    decoration: it is what this module NEEDS. Every type-scoped rule is a
    lookup on it, ADO will not create a work item without one, and no read-back
    shape carries it at the top level - a fetched row spells the type inside
    `fields`. So the question is now "a work-item-shaped payload whose work item
    type this module cannot see", which covers the decorated read-back and the
    batched row with one test. `fields` still has to be a dict, because that is
    what makes this a work item payload at all rather than some other object a
    caller passed by mistake.
    """
    if not isinstance(item, dict):
        return None
    if item.get("type"):
        return None
    if not isinstance(item.get("fields"), dict):
        return None
    seen = [k for k in _FETCHED_ONLY if k in item]
    read_back = ("" if not seen else
                 " It also carries %s, which only a work item READ BACK from "
                 "ADO has."
                 % (", ".join("`" + k + "`" for k in seen),))
    return ("this payload has no top-level `type`, so it is not an item about to "
            "be sent and cannot be graded as one. The expected shape is "
            "{\"type\": \"Task\", \"fields\": {...}, \"parent\": 123} - `type` "
            "and `parent` sit beside `fields`, not inside it. Graded as-is, "
            "`requiredFields` and `descriptionMustContain` are both keyed BY the "
            "work item type and so would check nothing at all, while "
            "`requireParent` would fire on an item that HAS a parent, because a "
            "fetched item's parent is at fields[\"System.Parent\"]. To grade an "
            "item that is ALREADY on the board, translate it first - "
            "`as_gradable_item()`, or `check-ado-item.py --fetched`.%s"
            % (read_back,))


def as_gradable_item(fetched):
    """A work item READ BACK from the board, in the shape this module grades.

    The status path has a real question to ask - does the item ALREADY on the
    board still conform - and the payload it holds is the one
    `rest_payload_reason` refuses. This is the translation, and it is code
    rather than a paragraph in `commands/sync.md` because every key in it has
    been got wrong once already: the work item type is at
    `fields["System.WorkItemType"]`, the parent at `fields["System.Parent"]`
    (ABSENT and never null when the board hangs it nowhere - `_ado_fetch` says
    so from a live read), and `fields` passes through untouched. A prose
    instruction naming three keys is a prose instruction nothing can check,
    which is how F106 got onto a board in the first place.

    NOTHING IS INVENTED. A row whose `System.WorkItemType` is missing - a
    narrower SELECT, a hand-built row - comes back with no `type` at all, so
    `rest_payload_reason` refuses it and the caller learns the type is unknown
    instead of being graded against the rules for a type nobody read. Same for
    the parent: the key is omitted rather than set to a falsy stand-in, because
    `requireParent` reads "absent" as the finding and a stand-in would read as
    an answer.
    """
    row = fetched if isinstance(fetched, dict) else {}
    fields = row.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    out = {"fields": fields}
    wit = fields.get("System.WorkItemType")
    if isinstance(wit, str) and wit.strip():
        out["type"] = wit.strip()
    ident = row.get("id")
    if ident is None:
        ident = fields.get("System.Id")
    if ident is not None:
        out["id"] = ident
    parent = fields.get("System.Parent")
    if parent is not None:
        out["parent"] = parent
    return out


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


def _typeless_rule_reason(wit, conventions):
    """Which of this board's rules a payload with no `type` hides from.

    `None` when the item names a type, or when the board scopes nothing by type
    and a typeless item can therefore be graded in full.

    THE OTHER HALF OF F106, and the more dangerous one. `requiredFields` and
    `descriptionMustContain` are both lookups on the work item type, so an item
    with no type sails past every entry in them and the answer comes back as
    "conforms". One payload produced a refusal on the only rule it could reach
    and a silent pass on the rules the board actually cares about - and a silent
    pass is worse than the refusal, because the refusal was at least argued with.
    A rule set that narrows to nothing has to say that it narrowed to nothing.
    """
    if wit:
        return None
    scoped = sorted(key for key in ("requiredFields", "descriptionMustContain")
                    if isinstance(conventions.get(key), dict)
                    and conventions[key])
    if not scoped:
        return None
    return ("item carries no top-level `type`, so %s could not be applied to it "
            "at all - this is a PARTIAL grade and not a clean one. The type "
            "belongs beside `fields`; a row fetched from the board spells it at "
            "fields[\"System.WorkItemType\"]" % (" and ".join(scoped),))


# THE BUG TYPE NAME IS NOT SPELLED IN THIS FILE, and that is the fix rather than
# an omission. `DEFAULT_BUG_TYPE` and an `unparented_types` lived here for a
# release while `_ado_parent.inventory` derived the same name inline, and the two
# spellings disagreed about a blank and about a padded name - so a bug ROW carried
# one type and `parent_rule_exemption` below looked for another, and the
# exemption stopped firing for the rows it exists for. Both now come from
# `_ado_parent.bug_type`, which is the module that reads every other name in
# `meta.ado.types`; the tuple reaches `parent_rule_exemption` as an ARGUMENT,
# which is what keeps these two layer-mates from needing an import between them.


# Read only as the first letter of a WORK ITEM TYPE NAME, which is the whole
# domain: `Bug`, `Task`, `Issue`, `Epic`, `Product Backlog Item` and whatever a
# board renamed them to. A tuple rather than a string, because `"" in "AEIOU"` is
# True and an empty type name would come back "an".
_VOWEL_INITIALS = ("A", "E", "I", "O", "U")


def _a_type(wit):
    """`a Task` / `an Issue` - the type name with the article that fits it.

    A helper for a one-character difference because the alternative shipped: the
    sentence below spelled `a %s` and a Basic-process board, whose bug type is
    `Issue`, read `a Issue` twice in the same paragraph. The first letter is the
    whole rule here - English's real exceptions (`an hour`, `a unicorn`) need a
    pronunciation this cannot have and a board would have to rename a type into
    one to meet them, which costs a wrong article and nothing else.
    """
    return "%s %s" % ("an" if wit[:1].upper() in _VOWEL_INITIALS else "a", wit)


def parent_rule_exemption(item, conventions, unparented=None):
    """Why `requireParent` was not applied to this item. `None` when it was.

    F120. The gate was type-agnostic and push is not: a payload with no parent
    was a violation whatever kind of item it was, while push supplies a parent
    for a phase and a task and never for a bug. A board that legitimately set
    `requireParent` therefore could not have a bug pushed to it at all, and the
    refusal arrived at CREATE time - after the plan, after the confirm - rather
    than where the contradiction lives, which is the configuration.

    THE ANSWER IS THE ONE `_ado_parent` ALREADY GAVE, not a new one. That module
    refuses to let `meta.ado.parentWorkItem` reach a bug, on the basis that "a
    push neither creates nor changes a bug's parent link"; reading
    `requireParent` as "every item THIS PLUGIN PARENTS" is the same fact stated
    from the gate's side. The alternative reading - every item, full stop - is
    coherent and would mean this connector simply cannot push a bug to a
    governed board, which is a product decision nobody took and one the refusal
    was making by accident.

    A SENTENCE AND NOT A SILENT SKIP. A board that asks for a parent on every
    card is asking for something the connector cannot supply, and a rule that
    quietly stopped applying would be exactly the silent pass the typeless half
    of F106 was: the reader is entitled to know the rule narrowed and why. It is
    NOT a violation, because refusing the create is the bug being fixed - so it
    travels beside the verdict rather than inside it, the same way
    `rest_payload_reason` does.

    `unparented` ABSENT MEANS THE CALLER DID NOT SAY, and nothing is exempt.
    That is deliberately the LOUD default: a caller which has not been taught
    the question gets the pre-F120 refusal, which is wrong but visible, rather
    than a pass nobody asked for. `_ado_parent.unparented_types(meta.ado)` is
    the answer, and `check-ado-item.py` is the caller that reads it.
    """
    if not isinstance(conventions, dict):
        return None
    if conventions.get("requireParent") is not True:
        return None
    if not isinstance(item, dict):
        return None
    wit = item.get("type")
    wit = wit.strip() if isinstance(wit, str) else ""
    if not wit or wit not in (unparented or ()):
        return None
    a_wit = _a_type(wit)
    return ("`requireParent` was NOT applied to this %s: a push creates %s "
            "card with no parent link and names no third kind to hang, so "
            "there is no resolved parent here for the rule to read. "
            "meta.ado.parentWorkItem is the AUDIT's own branch and does not "
            "reach %s either. If this board really wants every card inside "
            "the backlog, that is a gap between its standard and what this "
            "connector can supply - parent these by hand once they exist, or "
            "drop requireParent." % (wit, a_wit, a_wit))


def conformance_violations(item, conventions, unparented=None):
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

    `unparented` is the type names push creates without a parent link, from
    `_ado_parent.unparented_types(meta.ado)`. It narrows `requireParent` and
    nothing else, and the REASON it narrowed is `parent_rule_exemption`'s to
    give - asked here so the skip and the sentence cannot come apart, and
    printed by the caller, since an exemption nobody prints is the silent pass
    this module spends the rest of its length refusing.
    """
    if not isinstance(conventions, dict) or not conventions:
        return []
    if not isinstance(item, dict):
        return ["item must be an object, got %s" % (type(item).__name__,)]

    wit = item.get("type") or ""
    fields = item.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    out = []

    # First, because it says how much of what follows is a real answer. A caller
    # that reaches this function without `rest_payload_reason` - the panel, a
    # future command - still learns that the type-scoped half never ran.
    partial = _typeless_rule_reason(wit, conventions)
    if partial:
        out.append(partial)

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

    # The exemption is asked as a PREDICATE here and printed as a sentence by
    # the caller - one function, so a kind that stops being graded and the
    # reason given for it cannot disagree.
    if (conventions.get("requireParent") is True
            and parent_rule_exemption(item, conventions, unparented) is None):
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
