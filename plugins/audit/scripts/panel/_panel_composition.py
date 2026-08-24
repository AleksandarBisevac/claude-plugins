#!/usr/bin/env python3
"""
What the plan SAYS: the phase/task composition rows, the bug rows, the ADO
honesty banner and the areas registry -- everything `/api/state` and
`/api/areas` render out of the manifest itself.

Split out of `_panel_state.py` (U3.1). Layer 4, above `_panel_paths` (3).

Stdlib only, Python 3.8 compatible.
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

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (meta.areas registry + shared resolution)
import _branch                # noqa: E402  (the naming convention, one expansion path)
import _priority              # noqa: E402  (what a valid tier is, and who holds tier 1)
import _ado_parent            # noqa: E402  (where ONE item hangs, and the marker for 'no declaration')
import _panel_paths as _paths  # noqa: E402  (the shared base, at layer 3)

# Carried by module-level alias so every body below reads exactly as it did in
# `_panel_state`, where these were siblings rather than imports.
_within = _paths._within
_config_path = _paths._config_path
_manifest_path = _paths._manifest_path
read_config = _paths.read_config


# --- the plan as the panel shows it ---------------------------------------------
# A phase's `area` -> its tags. One implementation, in `_areas`, shared with
# audit-status: this file and that one each had their own copy of the same six
# lines, and the day one of them learned something (trimming, de-duplication, the
# registry lookup) the panel and the terminal would have disagreed about which
# phases are in an area.
_areas_of = _areas.areas_of

# `_proposals_view` USED TO SIT HERE, and it was the panel's own reading of
# `proposals[]` - including a `_parked_blockers` walk that answered the question
# `_proposals.unresolved_refs` already answers. It moved to `_proposals.py`
# (layer 4, imported by `_panel_state` at 5) when `/audit:propose list` stopped
# being prose a model rendered and became a table the script prints: two surfaces
# reading one array two ways is two answers about one manifest. A parked phase is
# also not part of the plan yet, which is why it was never part of the
# composition view even while it lived in this file.


def _bugs_view(manifest):
    """The bug rows the Overview lists, one per bug, already resolved.

    `status` here is the EFFECTIVE status — the same value `rollup()` counts in
    `bugs.byStatus`, computed by the same function — so a reader who clicks the
    "Fixed 2" pill gets exactly two rows. Deriving it a second time in JavaScript
    would be a second implementation of the bug<->task rule (a bug materialized
    into a task reads `fixed` once that task is done), and two implementations
    that can disagree is precisely how the panel's counts and its lists drift.
    `reported` keeps what the manifest actually stores, so a bug whose status is
    inherited from its task can say so instead of looking hand-edited."""
    as_ = _paths.status_facts()
    # The two indexes come from `_manifest_io` — the module that owns the shape —
    # rather than from a walk here; `phase_of_task` is why the enclosing `phases`
    # list this used to build is gone, since nothing else needed the phase bodies.
    # They are guaranteed to share a key set, which is what lets a row read both.
    task_by_id = _mio.tasks_by_id(manifest)
    task_phase = _mio.phase_of_task(manifest)
    out = []
    for b in (manifest.get("bugs") or []):
        if not isinstance(b, dict):
            continue
        eff = _mio.effective_bug_status(b, task_by_id)
        out.append({
            "id": b.get("id"), "title": b.get("title"),
            "status": eff,
            "reported": b.get("status"),
            "severity": b.get("severity"),
            # `open` and `high` are decided HERE, by the same two rules the rollup's
            # `open` / `openHighSeverity` counts use — CLOSED_BUG and the
            # high-or-worse severity set, which knows that critical, blocker, sev1
            # and p0 all mean high. A regex in the browser would be a third opinion
            # on the same question, and the "High severity, open" pill would
            # eventually count a different set than the list it filters to.
            "open": eff not in as_.CLOSED_BUG,
            "high": as_._is_high_severity(b.get("severity")),
            "taskId": b.get("taskId"),
            "phaseId": task_phase.get(b.get("taskId")),
            "reportedAt": b.get("reportedAt"),
        })
    return out


def _skills_of(task):
    """A task's skills as the panel SHOWS them — the THREE states kept apart.

    Explicit `null` is a conscious opt-out ("none applies" — it stops the area
    fallback, v0.37 B1) and stays None, so every display can say so instead of
    rendering it as empty. `[]` and an absent key both mean "unconsidered" and
    read as []; a junk-typed value reads as [] too (the validator names it).
    This is also the value a change row is written against: the client's form
    holds the same three states, so `[] -> [a]` and `null -> [a]` stay two
    different edits rather than a normalisation disagreement — which is the
    original reason this normaliser exists.
    """
    if isinstance(task, dict) and "skills" in task and task["skills"] is None:
        return None
    v = (task or {}).get("skills")
    return v if isinstance(v, list) else []


def _ado_status(manifest):
    """The ADO card's honesty-banner facts — MANIFEST EVIDENCE only, no network.

    The policy tab's rule applied to a second feature: the panel reports what
    the file proves (links /audit:sync wrote), never what the connector claims.
    `enabled`/`echo` are EFFECTIVE values (absent = on; a disabled connector
    reads echo off too) because the banner answers "what happens now", not
    "what is typed". Links count only int ids — the same shape the validator
    enforces — so junk never inflates the count."""
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado")
    configured = isinstance(ado, dict)
    ado = ado if configured else {}
    enabled = configured and ado.get("enabled") is not False
    linked = {"tasks": 0, "bugs": 0, "phases": 0}
    last = [None]

    def note(item, kind):
        link = item.get("ado") if isinstance(item, dict) else None
        if isinstance(link, dict) and isinstance(link.get("id"), int) \
                and not isinstance(link.get("id"), bool):
            linked[kind] += 1
            ts = link.get("lastSyncedAt")
            if isinstance(ts, str) and (last[0] is None or ts > last[0]):
                last[0] = ts

    # Phases are walked directly and tasks through `_mio.iter_tasks`: a phase can
    # carry an `ado` link with no tasks under it at all, and `iter_tasks` yields
    # nothing for such a phase. Two passes rather than one nested walk is free
    # here because every answer below is a count or a max — both order-free.
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict):
            note(ph, "phases")
    for _ph, t in _mio.iter_tasks(manifest):
        note(t, "tasks")
    for b in (manifest.get("bugs") or []):
        note(b, "bugs")
    return {"configured": configured,
            "enabled": enabled,
            "echo": enabled and ado.get("echo") is not False,
            "linked": linked, "lastSyncedAt": last[0]}


# --- where a phase hangs on the board, as the Composition table shows it --------
# The command that re-derives the candidate cache, spelled once: it appears in
# every state's sentence below, and three copies of a command name is three
# commands the day one of them is renamed.
_PARENT_REFRESH = "/audit:sync parents"


# --- the branch-naming convention, as the Composition card shows it -------------
def _branch_info(manifest):
    """The naming convention as it CURRENTLY resolves, plus a worked example.

    The example is computed HERE, in Python, from the value on disk — not in the
    browser as the operator types. A live preview would mean a second
    implementation of `_branch.expand`, whose whole point is a separator rule with
    cases; two copies of that is two answers, and the first time they disagree the
    branch git actually gets is the one nobody previewed. So the card shows what
    the SAVED settings produce, and the save re-renders it.

    `basis` rides along because `meta.branch` and `meta.branchPrefix` give
    different names from the same manifest, and a card that showed the template
    without saying which key was in force would be describing a convention that
    might not be the one running.
    """
    meta = manifest.get("meta") or {}
    cfg = _branch.config(meta)
    # A phase from the plan when there is one, so the example is THIS repo's, not
    # a stranger's. The fallback is labelled as an example rather than dressed up
    # as real - naming a phase that does not exist would be the more confusing half.
    sample = None
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") and ph.get("title"):
            sample = ph
            break
    made = _branch.compose(meta, sample or {"id": "P2", "title": "Chart export"},
                           initials="Jane Doe")
    return {
        "template": cfg["template"],
        "defaultType": cfg["defaultType"],
        "types": cfg["types"],
        "initials": cfg["initials"],
        "slugMaxLength": cfg["slugMaxLength"],
        "basis": cfg["basis"],
        "typeHelp": dict(_branch.TYPE_HELP),
        "example": made["name"],
        "exampleFrom": (sample or {}).get("id") or "P2 (no phase in the plan yet)",
        "exampleInitials": "Jane Doe",
        "violations": made["violations"],
    }


def _ado_parent_of(phase):
    """One phase's declaration, with ABSENT spelled as the marker.

    The three stored states are absent, null and an object, and the panel has to
    offer all three. A payload that simply left the key off would hand the
    browser `undefined` for absent and `null` for the declared nowhere - and
    `undefined` reads as "the server did not say", which is a fourth thing. So
    absent is spelled with `_ado_parent`'s own marker, the same object the patch
    sends back for it, and the browser reads one value with three shapes.
    """
    if _ado_parent.FIELD in phase:
        return phase.get(_ado_parent.FIELD)
    return _ado_parent.use_fallback()


def _candidate_row(item):
    """One cached candidate, or None when it carries no usable id.

    Int-only, `bool` refused first - the shape `_manifest_ado` grades and the
    same guard `_ado_status` applies to a link id, so junk in the cache cannot
    put an option in a menu that would be refused the moment it was saved.
    """
    if not isinstance(item, dict):
        return None
    wid = item.get("id")
    if isinstance(wid, bool) or not isinstance(wid, int) or wid <= 0:
        return None
    return {"id": wid, "type": item.get("type"), "title": item.get("title"),
            "state": item.get("state"), "url": item.get("url")}


def _candidate_cache(ado):
    """(state, rows, fetchedAt, basis) for `meta.ado.parentCandidates`.

    THE TWO EMPTIES ARE DIFFERENT ANSWERS AND THIS IS WHERE THEY SEPARATE.
    "nobody has fetched a list" and "the board had no parent-shaped item in
    scope" both reach a picker as zero options, and a menu that renders them
    identically says the second while meaning the first - a filter narrowed to
    nothing reading as all-clear. So the state is NAMED and each name carries
    the sentence that makes it checkable: the moment somebody looked, and the
    query that scoped the look.

    The manifest's own `basis` is quoted rather than paraphrased, and its
    ABSENCE is reported rather than papered over: a cache with no basis has to
    be trusted instead of checked, and saying so is the only honest option.
    """
    block = ado.get("parentCandidates")
    if not isinstance(block, dict):
        return ("absent", [], None,
                "no candidate list has been cached: nobody has asked this board "
                "yet, which is not the same answer as a board carrying no "
                "parent-shaped work item. Run %s to fetch one; until then a "
                "parent is named by typing its id." % (_PARENT_REFRESH,))
    rows = [r for r in [_candidate_row(x)
                        for x in (block.get("items") or [])] if r]
    fetched = block.get("fetchedAt")
    fetched = fetched if isinstance(fetched, str) and fetched else None
    declared = block.get("basis")
    declared = declared if isinstance(declared, str) and declared.strip() else None
    when = (" fetched %s" % (fetched,)) if fetched else " fetched at no recorded moment"
    # The stop is put back rather than assumed: the manifest's `basis` is
    # somebody else's sentence and may or may not carry one, and the clause that
    # follows it is a new sentence either way.
    how = ((" Scoped by: %s." % (declared.rstrip("."),)) if declared else
           (" The fetch recorded no basis, so how it was scoped is unknown - an "
            "empty list here cannot be told from a narrowed one."))
    if not rows:
        return ("empty", rows, fetched,
                "the cached candidate list is empty:%s, this board carried no "
                "parent-shaped work item in scope.%s Re-run %s to look again."
                % (when, how, _PARENT_REFRESH))
    return ("items", rows, fetched,
            "%d cached candidate(s),%s.%s Cached evidence and never an "
            "authority: an id missing from this list is not a wrong parent, "
            "only one created since the fetch. Re-run %s to refresh it."
            % (len(rows), when, how, _PARENT_REFRESH))


# The command that re-derives the connection evidence. Spelled once, beside
# `_PARENT_REFRESH` and for the same reason.
_CONNECT_REFRESH = "/audit:sync connect"


def _ado_connection(manifest):
    """What `/audit:sync connect` PROVED about this board, for the ADO card.

    THE CARD CANNOT RUN CONNECT AND MUST NOT PRETEND OTHERWISE. `connect`
    authenticates, and the panel authenticates nothing - so this is the same
    kind of block `_candidate_cache` is: manifest evidence, read-only, with the
    moment and the basis kept, and the command that re-derives it named in
    every state.

    WHY THE CARD SHOWED NOTHING ABOUT THIS BEFORE. `meta.ado.stateMap` is the
    single most likely first-push failure - the shipped defaults name Agile
    states, and a Scrum board refuses them - and the card let you edit the map
    while saying nothing about which process the board runs. The probe knows.
    So the `needs-map` state exists to put that answer where the control is,
    rather than in a terminal the person editing this card never saw.

    Four named states, because the ways of knowing nothing are not one way:
      absent     - connect has never run here.
      unknown    - it ran and could not tell which process (empty project, no
                   phase-level item yet, or two of them).
      needs-map  - it ran, this board is not Agile, and `stateMap` is not set.
      ok         - it ran, and nothing about the process is outstanding.
    """
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    block = ado.get("connection")
    if not isinstance(block, dict):
        return {"state": "absent", "process": None, "pbiType": None,
                "authPath": None, "fetchedAt": None,
                "basis": "this board has never been probed: nobody has run %s "
                         "here, so which process it runs - and therefore "
                         "whether stateMap is needed - is unknown rather than "
                         "settled. The connector may still be configured and "
                         "working; what is missing is the evidence, not the "
                         "connection." % (_CONNECT_REFRESH,),
                "refresh": _CONNECT_REFRESH}
    process = block.get("process")
    process = process if isinstance(process, str) and process else None
    pbi = block.get("pbiType")
    pbi = pbi if isinstance(pbi, str) and pbi else None
    auth = block.get("authPath")
    auth = auth if isinstance(auth, str) and auth else None
    fetched = block.get("fetchedAt")
    fetched = fetched if isinstance(fetched, str) and fetched else None
    when = ((" probed %s" % (fetched,)) if fetched
            else " probed at no recorded moment")
    # The auth PATH, never a credential and never a who: the card is a shared
    # screen, and the only useful fact here is which KIND of credential a later
    # 401 would be about.
    via = ((" Access was proven through the %r auth path." % (auth,)) if auth
           else " Which auth path answered was not recorded.")
    if process is None:
        return {"state": "unknown", "process": None, "pbiType": None,
                "authPath": auth, "fetchedAt": fetched,
                "basis": "access was proven,%s, but the process template could "
                         "not be told from this board - an empty project, one "
                         "carrying no phase-level item yet, or a customised "
                         "one carrying two.%s Until it is known, the shipped "
                         "stateMap defaults name Agile states and nothing here "
                         "says whether that fits. Re-run %s once the board has "
                         "a phase-level item on it."
                         % (when, via, _CONNECT_REFRESH),
                "refresh": _CONNECT_REFRESH}
    if block.get("stateMapNeeded") is True and ado.get("stateMap") is None:
        return {"state": "needs-map", "process": process, "pbiType": pbi,
                "authPath": auth, "fetchedAt": fetched,
                "basis": "this board runs the %s process,%s, and stateMap is "
                         "not set. The built-in defaults name Agile states, so "
                         "a task reaching done will be refused its state - set "
                         "the map below.%s"
                         % (process, when, via),
                "refresh": _CONNECT_REFRESH}
    return {"state": "ok", "process": process, "pbiType": pbi,
            "authPath": auth, "fetchedAt": fetched,
            "basis": "this board runs the %s process,%s; phase items are %s.%s "
                     "Cached evidence, so re-run %s after the board's process "
                     "or your credential changes."
                     % (process, when, ("%r" % (pbi,)) if pbi else "unrecorded",
                        via, _CONNECT_REFRESH),
            "refresh": _CONNECT_REFRESH}


def _ado_parents(manifest):
    """What the per-phase parent control needs, each half with its basis.

    `fallback` carries the ID AND THE SOURCE and deliberately not the sentence:
    `resolve` phrases its basis around the item it was asked about, and this
    call has no item - it asks the fallback question with an empty one. The
    sentence that names a phase is on that phase's own row, where it is true.
    Nothing here re-reads `parentWorkItem`: a second read would be a second
    opinion about where work hangs, which is what `resolve` exists to prevent.
    """
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    fallback = _ado_parent.resolve({}, ado)
    state, rows, fetched, basis = _candidate_cache(ado)
    return {"fallback": {"id": fallback["id"], "source": fallback["source"]},
            "candidates": rows, "fetchedAt": fetched,
            "cache": state, "basis": basis, "refresh": _PARENT_REFRESH}


def _resolved_parent(phase, ado):
    """`{id, source, basis}` for one phase - `resolve`'s answer, minus what a
    row cannot use. The declaration is already on the row and the warnings are
    the push plan's, so what is left is the answer and the sentence behind it."""
    res = _ado_parent.resolve(phase, ado)
    return {"id": res["id"], "source": res["source"], "basis": res["basis"]}


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
    ado = meta.get("ado") if isinstance(meta.get("ado"), dict) else {}
    phases_out, tasks_out = [], []
    # `phases_out` and `tasks_out` are separate flat lists, so splitting the old
    # nested walk in two changes neither one's order: the phase rows stay in
    # document order and `_mio.iter_tasks` yields the tasks in document order too.
    # The task rows need the owning phase's id, which arrives with the task.
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        review = ph.get("review") if isinstance(ph.get("review"), dict) else {}
        phases_out.append({"id": ph.get("id"), "title": ph.get("title"),
                           "status": ph.get("status"), "reviewModel": review.get("model"),
                           "area": _areas_of(ph.get("area")), "reviewSkill": ph.get("reviewSkill"),
                           # Through `_priority.tier_of`, never off the raw field:
                           # a value that is not a positive integer orders nothing,
                           # and a control showing it as a tier would offer to keep
                           # a pin the run does not honour.
                           "priority": _priority.tier_of(ph),
                           # Both halves, because neither is the other. The
                           # DECLARATION is what a control edits and what a save
                           # sends back; the RESOLUTION is what the phase
                           # actually hangs under right now, which for an absent
                           # declaration is the fallback and for an unusable one
                           # is nothing at all. A control showing only the first
                           # would let a reader edit a field without seeing what
                           # it currently does.
                           "adoParent": _ado_parent_of(ph),
                           "adoParentResolved": _resolved_parent(ph, ado)})
    for ph, t in _mio.iter_tasks(manifest):
        tasks_out.append({
            "id": t.get("id"), "title": t.get("title"),
            "phaseId": ph.get("id"), "status": t.get("status"),
            "model": t.get("model"),
            "skills": _skills_of(t),
            # ov (F-P-5): Overview shows what the REPORT's table shows, so
            # it needs the same four values. They ride the composition
            # payload rather than a second endpoint — this is one manifest
            # read either way, and the Composition tab ignores what it does
            # not edit. Timestamps stay whole; the client cuts them.
            "risk": t.get("risk"),
            "commit": t.get("commit"),
            "startedAt": t.get("startedAt"),
            "completedAt": t.get("completedAt"),
        })
    # Every skill name the AREAS declare, deduped in registry order — the other
    # half of what the manifest spells (task rows carry their own). Shipped so
    # the client's inventory hint (skillHints, the modelHints analog) can see
    # a name that lives only in meta.areas without a second endpoint.
    area_skills = []
    for entry in _areas.registry(manifest).values():
        sk = entry.get("skills")
        for s in (sk if isinstance(sk, list) else []):
            if isinstance(s, str) and s.strip() and s.strip() not in area_skills:
                area_skills.append(s.strip())
    return {
        "meta": {"reviewSkill": meta.get("reviewSkill"),
                 "buildCommands": meta.get("buildCommands"),
                 "branch": meta.get("branch"),
                 "ado": meta.get("ado")},
        "areaSkills": area_skills,
        "adoStatus": _ado_status(manifest),
        "adoParents": _ado_parents(manifest),
        "adoConnection": _ado_connection(manifest),
        "branchInfo": _branch_info(manifest),
        "phases": phases_out, "tasks": tasks_out,
    }


def areas_state(project):
    """`GET /api/areas` — the registry, and every tag the phases actually use.

    Both halves, because the two disagree in both directions and each disagreement
    is worth seeing: a tag no entry covers resolves to no reviewer and no skills
    (usually a typo), and a registered area no phase uses is either a plan that has
    not been written yet or a rename that only got done on one side.

    Every verdict here comes from `_areas` — the same module the validator, the
    doctor and the status renderer resolve through — so this endpoint cannot
    develop its own opinion about what is registered.
    """
    config = read_config(project)
    mpath = _manifest_path(project, config)
    out = {"path": os.path.relpath(mpath, project) if _within(project, mpath)
           else None,
           "areas": {}, "tags": [], "findings": [], "warnings": []}
    if not _within(project, mpath):
        out["findings"] = ["refused: manifest path escapes project"]
        return out
    try:
        manifest = _mio.load_manifest(mpath)
    except Exception as exc:
        out["findings"] = ["cannot read manifest: %s" % exc]
        return out
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    stored = meta.get("areas")
    out["areas"] = stored if isinstance(stored, dict) else {}
    f, w = _areas.validate_registry(stored)
    out["findings"], out["warnings"] = f, w
    reg = _areas.registry(manifest)
    used = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for tag in _areas.areas_of(ph.get("area")):
            used.setdefault(tag, []).append(ph.get("id"))
    for tag in sorted(set(reg) | set(used)):
        entry = reg.get(tag) or {}
        root = _areas.root_of(entry)
        out["tags"].append({
            "tag": tag,
            "registered": tag in reg,
            "phases": used.get(tag, []),
            "root": root or None,
            # Resolved here rather than in the browser: the panel already learned
            # once (c6) that a value it SHOWS and a value the server computes have
            # to come from one function or the two eventually disagree.
            "rootExists": bool(root) and os.path.isdir(os.path.join(project, root)),
            "description": entry.get("description"),
            "reviewSkill": entry.get("reviewSkill"),
            "skills": entry.get("skills") if isinstance(entry.get("skills"), list)
            else [],
        })
    return out


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_composition.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__panel_composition.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
