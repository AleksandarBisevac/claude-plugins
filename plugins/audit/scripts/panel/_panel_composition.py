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

def _proposals_view(manifest):
    """`proposals[]` as the panel's Proposals tab reads it.

    Its OWN state key rather than a corner of the composition view: that view is
    the plan EDITOR, and a parked phase is not part of the plan yet. Mixing the two
    is exactly the confusion F-P-32 was reported about.

    The payload travels WHOLE (phase title, task ids, titles, risk) so the tab can
    show what materializing would add without a second request, and `dropped`
    carries its reason - an archive nobody can read is a tombstone.
    """
    out = []
    for prop in (manifest.get("proposals") or []):
        if not isinstance(prop, dict):
            continue
        payload = prop.get("payload")
        phase = payload.get("phase") if isinstance(payload, dict) else None
        tasks = [t for t in ((phase or {}).get("tasks") or [])
                 if isinstance(t, dict)]
        out.append({
            "id": prop.get("id"),
            "name": prop.get("name"),
            "status": prop.get("status") or "proposed",
            "scope": prop.get("scope"),
            "benefit": prop.get("benefit"),
            "technicalNote": prop.get("technicalNote"),
            "openQuestions": [q for q in (prop.get("openQuestions") or [])
                              if isinstance(q, str)],
            "notes": prop.get("notes"),
            "droppedAt": prop.get("droppedAt"),
            "materializedAs": prop.get("materializedAs"),
            "materializedAt": prop.get("materializedAt"),
            "createdISO": prop.get("createdISO"),
            "hasPayload": isinstance(phase, dict) and bool(phase.get("id")),
            "phaseId": (phase or {}).get("id"),
            "phaseTitle": (phase or {}).get("title"),
            "tasks": [{"id": t.get("id"), "title": t.get("title"),
                       "risk": t.get("risk")} for t in tasks],
            # Which ids this payload waits on that only a PARKED payload owns.
            # Computed here so the tab can warn before the confirm, rather than
            # the reader discovering it from a refusal after the click.
            "waitsOn": _parked_blockers(manifest, phase),
        })
    return out


def _parked_blockers(manifest, phase):
    """Refs in this payload that resolve to nothing live. `[]` when there are none."""
    if not isinstance(phase, dict):
        return []
    live = set()
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            live.add(ph["id"])
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                live.add(t["id"])
    own = set([phase.get("id")]) | set(
        t.get("id") for t in (phase.get("tasks") or []) if isinstance(t, dict))
    refs, out = [], []
    for key in ("blockedBy", "dependsOn"):
        refs += [r for r in (phase.get(key) or []) if isinstance(r, str)]
        for t in (phase.get("tasks") or []):
            if isinstance(t, dict):
                refs += [r for r in (t.get(key) or []) if isinstance(r, str)]
    for ref in refs:
        if ref not in live and ref not in own and ref not in out:
            out.append(ref)
    return out


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


def _composition_view(manifest):
    meta = manifest.get("meta") or {}
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
                           "area": _areas_of(ph.get("area")), "reviewSkill": ph.get("reviewSkill")})
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
