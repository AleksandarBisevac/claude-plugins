#!/usr/bin/env python3
"""
Where ONE audit item hangs on somebody else's board, and whether that place can
be true.

`meta.ado.parentWorkItem` is a single integer for the WHOLE manifest, so every
phase an audit creates was forced under one Feature - this plugin overriding a
product owner's decision about where work belongs. A plan that audits three
subsystems usually belongs under three different Features, and the only way to
say that was to run three manifests.

So a phase (and a task, when `phaseWorkItems` is false) may declare its own
`adoParent`, and `meta.ado.parentWorkItem` becomes the FALLBACK it always
described itself as. Nothing is deprecated and nothing warns: "all of this audit
hangs under Feature X" is a real and common intent, and a warning on a key that
is still the right answer teaches people to skip warnings, which is how a real
refusal gets missed.

THREE STATES, THE SHAPE THIS REPO ALREADY READS EVERYWHERE (`meta.ado.tag`,
every `stateMap` value, `area.owner`):

    absent          fall through to meta.ado.parentWorkItem - byte-identical to
                    the behaviour before this module existed
    an object       that work item, and the object carries the BASIS: which type
                    it is, what it is called, and whether anybody looked
    explicit null   hangs under nothing, even when the fallback is set

`null` is what makes uncategorised a DECLARED outcome rather than an accident,
and it is why a declaration is an object and never a bare integer: two spellings
of one answer are two answers, and the hierarchy check, the push plan and the
panel all have to say where a parent came from.

WHY LAYER 1, AND WHY EVERYTHING ARRIVES AS AN ARGUMENT. `_manifest_crossrefs`
and `_manifest_ado` are both layer 2, so neither can import the other while both
need the SAME answer - as do `commands/sync.md` through `resolve-ado-parent.py`,
and the panel after that. A second expression of "which parent" would BE a second
parent. So this reaches nothing but `_output`: the connector config, the phase
list and the backlog payload all arrive as arguments, exactly as `_priority.py`
takes `TERMINAL` and the unmet map rather than deriving them.

IT OWNS ITS OWN VOCABULARY AND ITS OWN UNKNOWN-KEY LOOP for that same reason.
`_manifest_vocab._unknown_keys` is a layer-MATE, so importing it is the sideways
edge `layer_violations()` refuses; a short loop below is the price of the layer,
and it is cheaper than pushing this module up to L2 where half its consumers
could not reach it. The two loops are held to the same answer by a case rather
than by a comment claiming they agree.

WHAT ADO DOES NOT DO FOR YOU. Measured 2026-08-24 against a live board: an
API-created parent link is NOT checked against the project's own type hierarchy.
Work item 30 there is a Product Backlog Item whose `System.Parent` is 31, a Task
that was meant to be its child - the two ends the wrong way round, accepted on
write, and still sitting there. Nothing on the ADO side will ever report it, so
this module holds the rule or nobody does.

THE HIERARCHY IS ASKED, NEVER SHIPPED. Which type may parent which is a property
of the PROJECT: the payload that ranks Task under Product Backlog Item under
Feature under Epic also carries `bugsBehavior`, and a Bug is a requirement on one
board and a task on the next - both were measured on the same organization the
same afternoon. A table shipped here would be wrong on the second board and
confidently so. `levels_from_backlog_config` parses the project's answer; when
nobody has fetched it, every item reports `not verified` and the create proceeds,
because a missing basis is a thing to SAY and never a thing to guess around.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_parent.py`.
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

# The field, spelled once. Every reader and every writer asks this module for it,
# so a rename is one edit rather than a grep.
FIELD = "adoParent"

# Where a resolved parent came from. Named as a tuple because four surfaces render
# it and four string literals scattered across them is four vocabularies.
#   item   the item's own `adoParent` said so (an id, or an explicit null)
#   phase  the item is a task and `phaseWorkItems` puts it under its phase
#   meta   nothing on the item said anything, so `meta.ado.parentWorkItem` did
#   none   nothing anywhere said anything - an answer, and exit 0
PARENT_SOURCE = ("item", "phase", "meta", "none")

# The keys one `adoParent` declaration may carry. `id` is the ANSWER; everything
# else is the BASIS - what the id is, what it is called, and whether a person
# declared it or a pull observed it.
KNOWN_PARENT = ("id", "type", "title", "url", "source", "observedAt")

# How a declaration got there. Absent/null is an honest third answer -
# unrecorded - and is never backfilled with a guess, the rule `adoLink.origin`
# already follows for the same reason: putting a provenance on somebody else's
# record is the one wrong answer available.
DECLARED_SOURCE = ("declared", "imported")

# `bugsBehavior` -> which backlog a Bug is ranked with. MEASURED, not assumed: the
# same organization runs one project at `asRequirements` (Bug beside the Product
# Backlog Item) and another at `asTasks` (Bug beside the Task), and neither
# project's `workItemTypes` list names Bug at all - this field is the only thing
# that places it.
BUGS_BEHAVIOR = {"asRequirements": "requirementBacklog", "asTasks": "taskBacklog"}

# The two non-portfolio backlogs, lowest rank first. A tuple because the order is
# the rank order and reading it twice in two places is how the two would drift.
_BASE_BACKLOGS = ("taskBacklog", "requirementBacklog")


# --- the declaration: is this block sayable at all -------------------------------
def _positive_id(value):
    """`value` as a work item id, or None. `bool` is refused before `int`,
    because `True` is an `int` in Python and `id: true` is a typo rather than
    work item 1 - the same guard `_manifest_vocab._check_ado` learned at F15."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def unknown_declaration_keys(block, where):
    """Did-you-mean warnings for the keys inside one `adoParent`.

    A near-twin of `_manifest_vocab._unknown_keys`, and the twinning is a
    LAYER decision rather than an oversight: that module is a layer-mate, so
    importing it is the sideways edge `layer_violations()` refuses, and this
    module's whole value is being reachable from both layer-2 validators and a
    layer-7 door. The agreement between the two loops is pinned by a case
    (`test__ado_parent.py`), because a comment claiming two implementations
    agree is a comment, and this repo's own token formatter is the cautionary
    tale for that.
    """
    out = []
    if not isinstance(block, dict):
        return out
    lower = dict((k.lower(), k) for k in KNOWN_PARENT)
    for key in block:
        text = str(key)
        # "_" = internal, "$" = JSON-Schema keywords, "//" = comment convention
        if text in KNOWN_PARENT or text.startswith(("_", "$", "//")):
            continue
        hint = lower.get(text.lower())
        if hint:
            out.append("%s.%s: unknown key '%s' — did you mean '%s'?"
                       % (where, FIELD, text, hint))
        else:
            out.append("%s.%s: unknown key '%s' (typo? unknown keys are "
                       "ignored by the orchestrator)" % (where, FIELD, text))
    return out


def _basis_findings(block, where):
    """The declaration's BASIS fields — everything that is not the id."""
    out = []
    for key in ("type", "title", "url"):
        val = block.get(key)
        if key in block and val is not None and not isinstance(val, str):
            out.append("%s.%s.%s: must be a string or null, got %s"
                       % (where, FIELD, key, type(val).__name__))
    src = block.get("source")
    # A FINDING and not a warning, for `adoLink.origin`'s reason exactly: a
    # misspelled source reads as "unrecorded" on every surface downstream, which
    # is indistinguishable from the honest absence unless the validator refuses
    # it. `null` and absent both mean unrecorded and are left alone.
    if src is not None and src not in DECLARED_SOURCE:
        out.append("%s.%s.source: must be one of %s (or absent/null for "
                   "unrecorded), got %r"
                   % (where, FIELD, ", ".join(repr(v) for v in DECLARED_SOURCE),
                      src))
    seen = block.get("observedAt")
    if "observedAt" in block and seen is not None and not isinstance(seen, str):
        out.append("%s.%s.observedAt: must be an ISO timestamp string or null, "
                   "got %s" % (where, FIELD, type(seen).__name__))
    return out


def declaration_findings(item, where):
    """(findings, warnings) for one item's `adoParent`. The ONE shape check.

    ABSENT and `null` are both legal and produce nothing, because both are
    ANSWERS: absent means "use the fallback", null means "nowhere". Only a
    declaration that is present and unusable is a defect, and it is a FINDING
    rather than a warning because the alternative is an item silently falling
    through to `meta.ado.parentWorkItem` — landing on the board under a parent
    the file did not ask for, which is the exact override this feature exists
    to undo.
    """
    findings, warnings = [], []
    if not isinstance(item, dict) or FIELD not in item:
        return (findings, warnings)
    block = item.get(FIELD)
    if block is None:
        return (findings, warnings)
    if not isinstance(block, dict):
        findings.append("%s: %s must be an object {id, ...} or null (null = "
                        "hangs under nothing, even when "
                        "meta.ado.parentWorkItem is set), got %s"
                        % (where, FIELD, type(block).__name__))
        return (findings, warnings)
    warnings.extend(unknown_declaration_keys(block, where))
    if "id" not in block:
        findings.append("%s: %s requires an 'id' — the work item this hangs "
                        "under. Write null instead to declare that it hangs "
                        "under nothing." % (where, FIELD))
    elif _positive_id(block.get("id")) is None:
        findings.append("%s: %s.id must be a positive work item id (integer), "
                        "got %r — a config carrying \"103205\" as a string is a "
                        "typo worth naming rather than coercing, because "
                        "coercing hides it" % (where, FIELD, block.get("id")))
    findings.extend(_basis_findings(block, where))
    return (findings, warnings)


# --- resolution: the one function every surface calls ----------------------------
def _result(parent_id, source, basis, declaration=None, warnings=None):
    """One resolution, as a dict — never a tuple.

    A tuple would have had to be re-unpacked at every call site the day this
    grew its fifth member, and it already has five: the id, where it came from,
    the sentence saying so, the declaration behind it (which the plan and the
    hierarchy check both read for the parent's TYPE), and whatever had to be
    said out loud on the way.
    """
    return {"id": parent_id, "source": source, "basis": basis,
            "declaration": declaration if isinstance(declaration, dict) else None,
            "warnings": list(warnings or [])}


def _phase_result(item, phase, declared_key):
    """Rule 1: a task under a phase work item hangs under THAT phase."""
    warnings = []
    pid = phase.get("id") if isinstance(phase, dict) else None
    if declared_key:
        # INERT, and said out loud rather than dropped. A task carrying an
        # `adoParent` under `phaseWorkItems` is somebody expecting it to be
        # honoured; silently ignoring it is the no-op-on-unexpected-input that
        # leaves the author believing the file applied.
        warnings.append("task %s declares %s, which is INERT while "
                        "meta.ado.phaseWorkItems is on: the task hangs under "
                        "phase %s's own work item. Move the declaration to the "
                        "phase, or set phaseWorkItems to false."
                        % (item.get("id") or "?", FIELD, pid or "?"))
    link = phase.get("ado") if isinstance(phase, dict) else None
    linked = _positive_id(link.get("id")) if isinstance(link, dict) else None
    if linked is None:
        return _result(None, "phase",
                       "phase %s's work item does not exist yet — "
                       "meta.ado.phaseWorkItems is on, so this push creates the "
                       "phase item first and hangs the task under it"
                       % (pid or "?",), None, warnings)
    return _result(linked, "phase",
                   "phase %s's work item #%d — meta.ado.phaseWorkItems is on, "
                   "so tasks hang under their phase and never under "
                   "meta.ado.parentWorkItem" % (pid or "?", linked),
                   None, warnings)


def _declared_result(item, block, meta_parent):
    """Rules 2 and 3: the item's own declaration, id or explicit null."""
    where = item.get("id") or "?"
    if block is None:
        extra = ("" if meta_parent is None else
                 " — meta.ado.parentWorkItem #%d is deliberately NOT used here"
                 % (meta_parent,))
        return _result(None, "item",
                       "%s declares %s: null, so it hangs under nothing%s"
                       % (where, FIELD, extra))
    if not isinstance(block, dict):
        return _result(None, "item",
                       "%s carries an %s that is not an object and not null, so "
                       "no parent could be read from it — the manifest "
                       "validator names it as a finding"
                       % (where, FIELD),
                       None,
                       ["%s: %s is unusable, so this item was planned with NO "
                        "parent rather than silently falling back to "
                        "meta.ado.parentWorkItem" % (where, FIELD)])
    parent_id = _positive_id(block.get("id"))
    if parent_id is None:
        return _result(None, "item",
                       "%s declares an %s whose id is not a positive work item "
                       "id, so no parent could be read from it" % (where, FIELD),
                       block,
                       ["%s: %s.id is unusable, so this item was planned with "
                        "NO parent rather than silently falling back to "
                        "meta.ado.parentWorkItem" % (where, FIELD)])
    named = block.get("type") or block.get("title")
    return _result(parent_id, "item",
                   "%s declares %s #%d%s" % (where, FIELD, parent_id,
                                             (" (%s)" % (named,)) if named else ""),
                   block)


def resolve(item, ado=None, phase=None):
    """Where this one item hangs: {id, source, basis, declaration, warnings}.

    THE ONE FUNCTION, and every surface calls it — the validator, the push plan,
    `resolve-ado-parent.py` and the panel after them. Five rules, in order:

      1. a task, with `phaseWorkItems` on  -> its phase's work item. A task's own
         `adoParent` here is INERT and is WARNED about, never silently dropped
      2. `item.adoParent` is an object     -> that id, source `item`
      3. `item.adoParent` is null          -> no parent, source `item`
      4. absent, `parentWorkItem` set      -> that id, source `meta`
      5. neither                           -> no parent, source `none`

    Rule 5 IS AN ANSWER. Uncategorised work is a create and an exit 0 and a
    printed sentence — unless `conventions.requireParent` is on, which is the
    board saying otherwise, and which is graded where the plan can be seen.

    `phase` is the task's phase, or None when `item` IS a phase; `ado` is
    `meta.ado`, from which the two settings this needs are read in ONE place, so
    "absent phaseWorkItems means on" is decided here rather than at four call
    sites.
    """
    ado = ado if isinstance(ado, dict) else {}
    item = item if isinstance(item, dict) else {}
    meta_parent = _positive_id(ado.get("parentWorkItem"))
    if phase is not None and ado.get("phaseWorkItems") is not False:
        return _phase_result(item, phase, FIELD in item)
    if FIELD in item:
        return _declared_result(item, item.get(FIELD), meta_parent)
    if meta_parent is not None:
        return _result(meta_parent, "meta",
                       "nothing on %s declares a parent, so "
                       "meta.ado.parentWorkItem #%d is the fallback it has "
                       "always been" % (item.get("id") or "?", meta_parent))
    return _result(None, "none",
                   "neither %s nor meta.ado.parentWorkItem names a parent for "
                   "%s, so it is created uncategorised — a free-standing branch "
                   "nobody planning from that board will see"
                   % (FIELD, item.get("id") or "?"))


# --- the project's own hierarchy, asked rather than shipped ----------------------
def _rank_of(block):
    """One backlog level's rank, or None when the block is not one."""
    if not isinstance(block, dict):
        return None
    rank = block.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int):
        return None
    return rank


def _type_names(block):
    """The work item type names one backlog level admits, in payload order."""
    types = block.get("workItemTypes") if isinstance(block, dict) else None
    out = []
    for entry in (types if isinstance(types, list) else []):
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def levels_from_backlog_config(payload):
    """{"levels": {type name: rank}, "basis": ...} — or None when the payload
    is not a backlog configuration.

    `None` and an empty answer are DIFFERENT sentinels on purpose. A project
    whose payload could not be parsed has no basis for the type check and every
    item must report `not verified`; a dict with levels in it is a basis. A
    function that returned `{}` for both would let an unreadable response read
    as "this project ranks nothing", which is the shape that turns a guard off.

    Bug is placed by `bugsBehavior` and by nothing else, which is the half a
    hard-coded table gets wrong: neither measured project's `workItemTypes`
    list names Bug at all, and the same organization runs one project at
    `asRequirements` and another at `asTasks`.
    """
    if not isinstance(payload, dict):
        return None
    levels = {}
    ranks = {}
    for key in _BASE_BACKLOGS:
        block = payload.get(key)
        rank = _rank_of(block)
        if rank is None:
            continue
        ranks[key] = rank
        for name in _type_names(block):
            levels[name] = rank
    portfolios = payload.get("portfolioBacklogs")
    for block in (portfolios if isinstance(portfolios, list) else []):
        rank = _rank_of(block)
        if rank is None:
            continue
        for name in _type_names(block):
            levels[name] = rank
    if not levels:
        return None
    behavior = payload.get("bugsBehavior")
    placed = BUGS_BEHAVIOR.get(behavior) if isinstance(behavior, str) else None
    if placed in ranks and "Bug" not in levels:
        levels["Bug"] = ranks[placed]
    return {"levels": levels,
            "basis": ("ranks read from this project's own backlog "
                      "configuration (az devops invoke --area work --resource "
                      "backlogconfiguration), bugsBehavior=%s: %s"
                      % (behavior if isinstance(behavior, str) else "unset",
                         ", ".join("%s=%d" % (n, r)
                                   for n, r in sorted(levels.items()))))}


# --- the inventory every check and every plan reads ------------------------------
def _work_item_id(item):
    """The item's OWN work item id, or None when it is not linked yet."""
    link = item.get("ado") if isinstance(item, dict) else None
    return _positive_id(link.get("id")) if isinstance(link, dict) else None


def _parent_type(result, phase_type):
    """The TYPE of the resolved parent, or None when nobody has said.

    Two sources and no third: a declaration that recorded what it pointed at,
    and a phase work item whose type `meta.ado.types.pbi` already names.
    `meta.ado.parentWorkItem` carries no type at all, and `parentCandidates` is
    a convenience for a dropdown rather than an authority, so an item under the
    manifest-wide fallback reports `not verified` — which is the honest answer
    and the one that keeps the create moving.
    """
    if result.get("source") == "phase":
        return phase_type
    declared = result.get("declaration")
    kind = declared.get("type") if isinstance(declared, dict) else None
    return kind if isinstance(kind, str) and kind.strip() else None


def inventory(phases, ado=None):
    """{"rows": [...], "warnings": [...]} — every phase and task with its parent.

    The rows are what `hierarchy_violations` and `plan_lines` both read, so the
    walk happens ONCE and the two cannot disagree about which items were in the
    plan. Each row is {kind, id, workItemId, type, parent, parentType, source,
    basis, declaration}.
    """
    ado = ado if isinstance(ado, dict) else {}
    types = ado.get("types")
    types = types if isinstance(types, dict) else {}
    phase_type = types.get("pbi") if isinstance(types.get("pbi"), str) else None
    task_type = types.get("task") if isinstance(types.get("task"), str) else "Task"
    rows, warnings = [], []
    for phase in (phases if isinstance(phases, list) else []):
        if not isinstance(phase, dict):
            continue
        result = resolve(phase, ado=ado)
        rows.append(_row("phase", phase, phase_type, result, phase_type))
        warnings.extend(result["warnings"])
        tasks = phase.get("tasks")
        for task in (tasks if isinstance(tasks, list) else []):
            if not isinstance(task, dict):
                continue
            tresult = resolve(task, ado=ado, phase=phase)
            rows.append(_row("task", task, task_type, tresult, phase_type))
            warnings.extend(tresult["warnings"])
    return {"rows": rows, "warnings": warnings}


def _row(kind, item, own_type, result, phase_type):
    """One inventory row. A free function so a case can build one by hand."""
    return {"kind": kind, "id": item.get("id"),
            "workItemId": _work_item_id(item), "type": own_type,
            "parent": result["id"], "parentType": _parent_type(result, phase_type),
            "source": result["source"], "basis": result["basis"],
            "declaration": result["declaration"]}


# --- the hierarchy check, in three tiers -----------------------------------------
def _edges(rows):
    """work item id -> the parent this manifest gives it. The declared graph."""
    out = {}
    for row in rows:
        own = row.get("workItemId")
        if own is None:
            continue
        out[own] = row.get("parent")
    return out


def _loop_from(start, own, edges):
    """The chain from `start` back to `own`, or None when there is no loop.

    Walks UP the parent edges, because "the parent is something this manifest
    hangs under me" is exactly "walking up from the parent reaches me". The
    `seen` set is not an optimisation: a loop that does not include `own` would
    otherwise spin forever, and a validator that hangs is worse than one that
    is wrong.
    """
    chain, seen, cursor = [], set(), start
    while isinstance(cursor, int) and cursor not in seen:
        chain.append(cursor)
        if cursor == own:
            return chain
        seen.add(cursor)
        cursor = edges.get(cursor)
    return None


def _entry(code, tier, row, message):
    return {"code": code, "tier": tier, "kind": row.get("kind"),
            "id": row.get("id"), "parent": row.get("parent"), "message": message}


def _structural_entry(row, edges, by_item):
    """Tier A for one row, or None. Offline, and it always has a basis."""
    own, parent = row.get("workItemId"), row.get("parent")
    if parent is None:
        return None
    if own is not None and parent == own:
        return _entry("A1", "A", row,
                      "%s %s declares its own work item #%d as its parent — an "
                      "item cannot hang under itself"
                      % (row.get("kind"), row.get("id") or "?", own))
    if own is None:
        # Not linked yet, so this manifest gives it no node in the graph and no
        # loop through it can be drawn. SAID here rather than left implied: the
        # tier that "always has a basis" has one because the ids exist.
        return None
    loop = _loop_from(parent, own, edges)
    if loop is None:
        return None
    others = [by_item.get(node) for node in loop if node != own]
    kinds = [r.get("kind") for r in others if r]
    if len(loop) == 2 and row.get("kind") == "phase" and kinds == ["phase"]:
        other = others[0] if others else None
        return _entry("A3", "A", row,
                      "phase %s and phase %s each declare the other's work item "
                      "as their parent (#%d and #%d) — neither can be created "
                      "inside the other"
                      % (row.get("id") or "?",
                         (other or {}).get("id") or "?", own, parent))
    named = ", ".join("#%d" % (node,) for node in loop)
    return _entry("A2", "A", row,
                  "%s %s would hang under #%d, and this manifest already hangs "
                  "#%d under %s's own work item #%d (chain %s) — the link would "
                  "close a loop, and ADO will accept it: an API-created parent "
                  "link is not checked against the process hierarchy"
                  % (row.get("kind"), row.get("id") or "?", parent, parent,
                     row.get("id") or "?", own, named))


def _level_entry(row, levels):
    """Tier B for one row: (kind, entry). `kind` is one of the three answers."""
    child, parent_kind = row.get("type"), row.get("parentType")
    if levels is None:
        return ("unverified",
                _entry("B0", "B", row,
                       "%s %s hangs under #%d and the type levels were never "
                       "fetched — no basis for the hierarchy check "
                       "(run /audit:sync parents)"
                       % (row.get("kind"), row.get("id") or "?",
                          row.get("parent"))))
    child_rank = levels.get(child) if isinstance(child, str) else None
    parent_rank = levels.get(parent_kind) if isinstance(parent_kind, str) else None
    if child_rank is None or parent_rank is None:
        unranked = child if child_rank is None else parent_kind
        return ("unverified",
                _entry("B0", "B", row,
                       "%s %s hangs under #%d and %s has no rank in "
                       "meta.ado.hierarchy — not verified"
                       % (row.get("kind"), row.get("id") or "?",
                          row.get("parent"),
                          ("its own type" if unranked is None
                           else "type %r" % (unranked,)))))
    if parent_rank < child_rank:
        return ("refusal",
                _entry("B1", "B", row,
                       "%s %s is a %s (backlog rank %d) and would hang under "
                       "#%d, a %s (rank %d) — a parent must sit ABOVE its child "
                       "on this project's backlog, and this is the pair the "
                       "wrong way round"
                       % (row.get("kind"), row.get("id") or "?", child,
                          child_rank, row.get("parent"), parent_kind,
                          parent_rank)))
    if parent_rank == child_rank:
        # WARN, NEVER REFUSE, and the reason is a case that works: a Bug under a
        # Product Backlog Item is rank 2 under rank 2 wherever bugsBehavior is
        # asRequirements, and teams do it deliberately. A checker that refuses a
        # deliberate, legal arrangement gets switched off, which is the failure
        # mode a conformance check exists to avoid.
        return ("warning",
                _entry("B2", "B", row,
                       "%s %s is a %s and would hang under #%d, another %s "
                       "(both backlog rank %d) — legal on this project and "
                       "often deliberate, so this is a note and not a refusal"
                       % (row.get("kind"), row.get("id") or "?", child,
                          row.get("parent"), parent_kind, child_rank)))
    return ("ok", None)


def hierarchy_violations(rows, levels=None):
    """Every way a resolved parent cannot be true.

    Returns {"refusals", "warnings", "unverified", "checked"} — four keys
    because there are four outcomes and collapsing any two of them loses the
    distinction the whole feature turns on. `checked` is there so "nothing was
    wrong" and "nothing was looked at" cannot print the same way.

    TIER A IS STRUCTURAL, OFFLINE AND ALWAYS HAS A BASIS: it reads only ids this
    manifest already carries, so it needs no network, no cache and no
    permission. TIER B needs `levels`, and with none it says `not verified` for
    every item rather than guessing — the create proceeds either way, because a
    missing basis is not evidence of a defect.

    A row refused by tier A is NOT graded by tier B. Its ranks are beside the
    point once the link closes a loop, and two refusals for one item would make
    the plan's count read as two problems.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    edges = _edges(rows)
    by_item = dict((r["workItemId"], r) for r in rows
                   if r.get("workItemId") is not None)
    refusals, warnings, unverified = [], [], []
    checked = 0
    for row in rows:
        if row.get("parent") is None:
            continue                      # uncategorised: not a hierarchy question
        checked += 1
        structural = _structural_entry(row, edges, by_item)
        if structural is not None:
            refusals.append(structural)
            continue
        kind, entry = _level_entry(row, levels)
        if kind == "refusal":
            refusals.append(entry)
        elif kind == "warning":
            warnings.append(entry)
        elif kind == "unverified":
            unverified.append(entry)
    return {"refusals": refusals, "warnings": warnings,
            "unverified": unverified, "checked": checked}


# --- the sentences every surface prints ------------------------------------------
def plan_lines(rows, violations=None):
    """The parent block a push plan prints, as lines.

    BUILT HERE rather than in each renderer, for `_priority.note`'s reason: the
    whole DRY claim of this feature is one set of sentences reaching the confirm
    gate, the door, the validator's neighbours and the panel, instead of four
    renderings that drift.

    BOTH COUNTS ARE PRINTED AT ZERO. A number that appears only on bad news
    cannot be told apart from a number nobody computed, and the operator reading
    a confirm gate has no other way to learn that the check ran.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    result = violations if isinstance(violations, dict) else \
        hierarchy_violations(rows)
    refused = dict((e.get("id"), e) for e in result.get("refusals") or [])
    uncategorised = [r for r in rows if r.get("parent") is None]
    out = ["parents: %d item(s), %d refused by the hierarchy check, "
           "%d uncategorised (no parent anywhere)"
           % (len(rows), len(result.get("refusals") or []), len(uncategorised))]
    for row in rows:
        target = ("#%d" % (row["parent"],)) if row.get("parent") is not None \
            else "none"
        out.append("  %s %s -> %s -- %s"
                   % (row.get("kind"), row.get("id") or "?", target,
                      row.get("basis") or "(no basis recorded)"))
        entry = refused.get(row.get("id"))
        if entry is not None:
            out.append("    REFUSED [%s] %s" % (entry["code"], entry["message"]))
    out.append("  hierarchy: %d link(s) checked, %d not verified"
               % (result.get("checked") or 0,
                  len(result.get("unverified") or [])))
    for entry in (result.get("unverified") or []):
        out.append("    NOT VERIFIED %s" % (entry["message"],))
    for entry in (result.get("warnings") or []):
        out.append("    NOTE [%s] %s" % (entry["code"], entry["message"]))
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
        print("_ado_parent.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__ado_parent.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
