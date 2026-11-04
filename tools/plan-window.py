#!/usr/bin/env python3
"""
Write a WINDOW of a sharded plan: the phases a rendered page needs to show every
shape the whole plan has, and nothing else.

    tools/plan-window.py <plan> <dst>

The report leg in `tools/verify.sh` drives every phase a page holds at every rung
of a width ladder, so rendering this repository's whole plan made its cost grow
with each merged phase. The window is written as a project of its own under
`<dst>`, at the plan's own record-shaped path, with the evidence ledger and the
project config beside it, so the renderer resolves `<dst>` as the window's
project the way it resolves the checkout. It then asks the report's evidence
reader of the plan and of the window, and fails when any subject the window
keeps reads differently or the chip sets differ. The third place - the
full-gate verdict the renderer reads per merged phase, a question to git - is
not part of either reading, and the command names the merged phases it leaves
uncompared rather than letting its agreement read as covering them.

BOTH READINGS COME FROM ONE SNAPSHOT. The plan, its shards, the ledger and the
config are copied once into a scratch project, and the selection, the window and
both evidence readings are taken from that copy. In a checkout where a drive is
appending ledger rows and rewriting the plan while this runs, two reads of the
live files at two moments could disagree with no defect behind it.

This file carries no `--selftest` of its own; its cases live in
`tests/test_plan_window.py`, against a fixture plan whose shape is fixed there.
Exit codes: 0 the window was written and reads as the plan does - 1 it reads
differently - 2 usage error, or a plan this cannot window.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout (the shape `tools/bench-report.py` uses).
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402  (the anchor: install_path, safe_stdio, project_of_manifest)

_output.install_path()

import _evidence_io  # noqa: E402  (the ledger's location and the boundary)
import _evidence_view  # noqa: E402  (the reader render-report.py asks)
import _manifest_io  # noqa: E402  (the assembled plan the reader reads)

SNAPSHOT_PREFIX = "plan-window-snapshot-"
USAGE = "usage: plan-window.py <plan> <dst>\n"

# A key that is a NAME (the schema's field names all are) is part of the shape. A
# dict holding any other key is a map keyed by DATA - `tests.falsifiers` is keyed
# by sentences - and reading each of its keys as a field would make every phase
# carrying one look new, so such a dict is read as one map, spelled `{}`.
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --- the selection ------------------------------------------------------------
# WHAT THE WINDOW KEEPS, and the check that fails when each arm misses:
#
#   every phase that is not done                     (nothing - it is the subject)
#   every phase carrying a key path, a status, or an evidence status or flag no
#     kept phase carries                             (the evidence comparison, for
#                                                     an evidence word; NOTHING for
#                                                     a manifest key or status, so
#                                                     that arm is the reading of
#                                                     this code and of its suite)
#   every phase a kept phase's blockedBy, or a kept task's dependsOn or blockedBy,
#     points into, transitively                      (validation of the window)
#
# A KEY PATH, NOT A TOP-LEVEL KEY. Reading only the keys a phase or a task has at
# its top level dropped the shapes below them - the object form of `outcome`, a
# render branch of its own, and `tests.falsifiers` - while every check passed.
#
# NO FIXED COUNT OF RECENT DONE PHASES. One stood here, and by construction it can
# add no key path, status or evidence word: the shape arm already keeps a phase
# carrying each of those, so a phase kept for its age alone brings only volume -
# more done phases and rows at each width rung. Volume is deliberately not what
# the window keeps; it is the cost the window exists to cut. A surface a recently
# merged phase exercises is a key path or a status on it, which the shape arm
# keeps whatever the phase's age.
def key_paths(obj, prefix=""):
    """Every key path under `obj`: `a.b` for a key inside a key, `a[].b` through a
    list's items, `a.{}` for the keys of a map keyed by data."""
    out = set()
    if isinstance(obj, dict):
        fields = all(isinstance(k, str) and _FIELD.match(k) for k in obj)
        for k in sorted(obj, key=str):
            name = k if fields else "{}"
            path = "%s.%s" % (prefix, name) if prefix else name
            out.add(path)
            out |= key_paths(obj[k], path)
    elif isinstance(obj, list):
        for item in obj:
            out |= key_paths(item, prefix + "[]")
    return out


def _words(view):
    return (view["key"], [k for k, _w in view["flags"]])


def shape(shard, reading):
    """The set of things one phase shows a page: its key paths and its tasks',
    their statuses, and the evidence status and flags `reading` gives the phase and
    each task (`reading` None for a plan with no evidence)."""
    body = dict((k, v) for k, v in shard.items() if k != "tasks")
    got = set(("phase", p) for p in key_paths(body))
    got.add(("phase-status", shard.get("status")))
    views = []
    phases = (reading or {}).get("phases") or {}
    tasks = (reading or {}).get("tasks") or {}
    if shard.get("id") in phases:
        views.append(phases[shard["id"]]["own"])
    for task in shard.get("tasks") or []:
        got |= set(("task", p) for p in key_paths(task))
        got.add(("task-status", task.get("status")))
        if task.get("id") in tasks:
            views.append(tasks[task["id"]])
    for key, flags in (_words(v) for v in views):
        got.add(("evidence", key))
        got |= set(("evidence-flag", f) for f in flags)
    return got


def references(shard, owner):
    """The phases `shard` points into: its own blockedBy, and its tasks' dependsOn
    and blockedBy read through `owner` (task id -> phase id). An id no phase owns is
    returned as written, so a caller can tell it from a phase."""
    out = set(shard.get("blockedBy") or [])
    for task in shard.get("tasks") or []:
        for key in ("dependsOn", "blockedBy"):
            out |= set(owner.get(r, r) for r in task.get(key) or [])
    return out


def select(order, shards, reading):
    """The set of phase ids the window keeps. `order` is the plan's phase order,
    `shards` phase id -> shard, `reading` the evidence reading of the whole plan."""
    keep = set(pid for pid in order if shards[pid].get("status") != "done")
    seen = set()
    for pid in order:
        if pid in keep:
            seen |= shape(shards[pid], reading)
    for pid in order:
        if pid not in keep:
            new = shape(shards[pid], reading) - seen
            if new:
                keep.add(pid)
                seen |= new
    owner = dict((t["id"], pid) for pid in order
                 for t in shards[pid].get("tasks") or [])
    todo = sorted(keep)
    while todo:
        for ref in references(shards[todo.pop()], owner):
            if ref in shards and ref not in keep:
                keep.add(ref)
                todo.append(ref)
    return keep


def narrow(plan, shards, keep):
    """A copy of the plan index holding only what `keep` keeps: its phases, the
    fileIndex entries of kept tasks, the bugs on a kept task or on none, and the
    proposals that became a kept phase or none."""
    ids = set(t["id"] for pid in keep for t in shards[pid].get("tasks") or [])
    out = dict(plan)
    out["phases"] = [p for p in plan["phases"] if p["id"] in keep]
    out["fileIndex"] = dict((f, [t for t in ts if t in ids])
                            for f, ts in (plan.get("fileIndex") or {}).items()
                            if any(t in ids for t in ts))
    out["bugs"] = [b for b in plan.get("bugs") or []
                   if b.get("taskId") is None or b.get("taskId") in ids]
    out["proposals"] = [x for x in plan.get("proposals") or []
                        if x.get("materializedAs") is None
                        or x.get("materializedAs") in keep]
    return out


# --- the project on disk ----------------------------------------------------------
def _read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_text(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _copy_file(src, dst):
    parent = os.path.dirname(dst)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    shutil.copyfile(src, dst)


def _layout(plan_path):
    """`{project, plan, ledger, config}` for the plan at `plan_path`, each path but
    the project's relative to the project. The ledger is where the evidence reader
    resolves it; one outside the project cannot be carried into a window."""
    project, config = _evidence_io.project_config_for(plan_path)
    ledger = _evidence_io.evidence_dir(project, config)
    rel_ledger = os.path.relpath(ledger, project)
    if rel_ledger == os.pardir or rel_ledger.startswith(os.pardir + os.sep):
        raise ValueError("the evidence ledger %s is outside the project %s, so a "
                         "window cannot carry it" % (ledger, project))
    return {"project": project,
            "plan": os.path.relpath(os.path.abspath(plan_path), project),
            "ledger": rel_ledger,
            "config": os.path.join(".claude", "audit.config.json")}


def _phase_stubs(plan):
    stubs = plan.get("phases") or []
    inline = [p.get("id") for p in stubs if "shard" not in p]
    if inline:
        raise ValueError("phase(s) %s carry no shard, and this windows a sharded "
                         "plan only" % (", ".join(str(i) for i in inline),))
    return stubs


def _carry(layout, root, shard_rels):
    """Copy, from `layout`'s project into `root`, the named shards, the ledger and
    the config, each at its own relative path. A `.claude/` is made in `root`
    whatever the config, so `root` resolves as its own project wherever it sits."""
    src = layout["project"]
    plan_dir = os.path.dirname(layout["plan"])
    for rel in shard_rels:
        _copy_file(os.path.join(src, plan_dir, rel), os.path.join(root, plan_dir, rel))
    ledger = os.path.join(src, layout["ledger"])
    if os.path.isdir(ledger):
        shutil.copytree(ledger, os.path.join(root, layout["ledger"]))
    if not os.path.isdir(os.path.join(root, ".claude")):
        os.makedirs(os.path.join(root, ".claude"))
    config = os.path.join(src, layout["config"])
    if os.path.isfile(config):
        shutil.copyfile(config, os.path.join(root, layout["config"]))


def snapshot(plan_path, root):
    """Copy the plan, every shard it names, its ledger and its config into `root`
    as a project of the same layout, and return the copied plan's path. The plan
    file is read once and written from those bytes, so the shards copied are the
    ones that reading names."""
    layout = _layout(plan_path)
    with io.open(plan_path, encoding="utf-8") as fh:
        text = fh.read()
    stubs = _phase_stubs(json.loads(text))
    out = os.path.join(root, layout["plan"])
    _write_text(out, text)
    _carry(layout, root, [p["shard"] for p in stubs])
    return out


def write_window(plan_path, plan, keep, dst):
    """Write the window of the plan at `plan_path` into `dst`: the narrowed index
    `plan`, the shards of `keep`, the ledger and the config. Returns its path. A
    project theme FILE is not carried, so one added beside the config would be
    missing from the window."""
    layout = _layout(plan_path)
    out = os.path.join(dst, layout["plan"])
    _write_text(out, json.dumps(plan, indent=2))
    _carry(layout, dst, [p["shard"] for p in plan["phases"] if p["id"] in keep])
    return out


def evidence(plan_path):
    """The reading render-report.py makes of the plan, through the same reader
    with the same boundary - every part of it but the third place.

    The renderer also hands the reader `full_run`, a per-merged-phase verdict on
    whether a recorded full-gate run's head contains the merge, and that is a
    question to git. Neither the snapshot nor the window is a checkout, so no
    `full_run` is passed here and neither reading carries a `fullRun` entry; the
    phases this leaves uncompared are `uncompared_third_place`'s, and the command
    names them."""
    return _evidence_view.load_evidence(
        _manifest_io.load_manifest(plan_path), plan_path,
        boundary=_evidence_io.boundary_for(plan_path))


def uncompared_third_place(manifest):
    """The ids of the phases in `manifest` the renderer asks the third-place
    question of - every merged phase, when the plan declares a runnable full
    gate - which `evidence` does not read. `[]` when the plan declares none,
    the case where the renderer asks nothing either."""
    if not _evidence_io.full_gate_commands(manifest):
        return []
    return [str(p["id"]) for p in (manifest.get("phases") or [])
            if _evidence_io.merged_phase(p)]


# --- the comparison -----------------------------------------------------------
def disagreements(full, window):
    """Each way the window's reading differs from the full plan's: presence, the
    chip sets, and per subject - the chip sets alone could agree while a task the
    window kept had lost its run to another status."""
    if full is None or window is None:
        return ([] if full is None and window is None else
                ["evidence: the full plan's reading is %s, the window's is %s"
                 % ("absent" if full is None else "present",
                    "absent" if window is None else "present")])
    out = []
    for field in ("keys", "flags"):
        if window.get(field) != full.get(field):
            out.append("%s: full plan %r, window %r"
                       % (field, full.get(field), window.get(field)))
    pairs = [("task", sid, v, (full.get("tasks") or {}).get(sid))
             for sid, v in sorted((window.get("tasks") or {}).items())]
    theirs_phases = full.get("phases") or {}
    pairs += [("phase", sid, v["own"],
               theirs_phases[sid]["own"] if sid in theirs_phases else None)
              for sid, v in sorted((window.get("phases") or {}).items())]
    for kind, sid, mine, theirs in pairs:
        if theirs is None or _words(mine) != _words(theirs):
            out.append("%s %s: full plan %r, window %r"
                       % (kind, sid, theirs and _words(theirs), _words(mine)))
    return out


# --- the command --------------------------------------------------------------
def build(snap_plan, dst):
    """Select and write the window of the snapshot at `snap_plan` into `dst`, and
    read both. Returns `{keep, phases, tasks, keptTasks, full, window, drift,
    uncompared}`, `uncompared` being the window's phases whose third-place
    verdict neither reading carries; every file it reads is the snapshot's or the
    window's."""
    full = evidence(snap_plan)
    plan = _read_json(snap_plan)
    stubs = _phase_stubs(plan)
    base = os.path.dirname(snap_plan)
    order = [p["id"] for p in stubs]
    shards = dict((p["id"], _read_json(os.path.join(base, p["shard"])))
                  for p in stubs)
    keep = select(order, shards, full)
    narrowed = narrow(plan, shards, keep)
    window_plan = write_window(snap_plan, narrowed, keep, dst)
    window = evidence(window_plan)
    tasks = dict((pid, len(shards[pid].get("tasks") or [])) for pid in order)
    return {"keep": keep, "phases": len(order), "tasks": sum(tasks.values()),
            "keptTasks": sum(tasks[pid] for pid in keep), "full": full,
            "window": window,
            "drift": disagreements(full, window),
            "uncompared": uncompared_third_place(
                _manifest_io.load_manifest(window_plan))}


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(USAGE)
        return 2
    plan_path, dst = argv
    if not os.path.isfile(plan_path):
        sys.stderr.write("plan-window: no plan at %s\n%s" % (plan_path, USAGE))
        return 2
    scratch = tempfile.mkdtemp(prefix=SNAPSHOT_PREFIX)
    try:
        try:
            got = build(snapshot(plan_path, scratch), dst)
        except ValueError as exc:
            sys.stderr.write("plan-window: %s\n" % (exc,))
            return 2
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("live plan window: %d of %d phases, %d of %d tasks"
          % (len(got["keep"]), got["phases"], got["keptTasks"], got["tasks"]))
    if got["uncompared"]:
        print("live plan window: the third-place verdict of %d merged phase(s) "
              "is not compared (%s) - it asks git whether a full run's head "
              "contains the merge, and neither the snapshot nor the window is a "
              "checkout"
              % (len(got["uncompared"]), ", ".join(got["uncompared"])))
    if got["drift"]:
        sys.stderr.write("live plan window: %d evidence reading(s) differ from the "
                         "full plan's, so the page would not show the plan's "
                         "evidence:\n" % (len(got["drift"]),))
        for line in got["drift"][:12]:
            sys.stderr.write("  %s\n" % (line,))
        return 1
    window = got["window"]
    print("live plan window: evidence of %d task(s) and %d phase(s) reads as the "
          "full plan's, over %s ledger file(s)"
          % (len(window["tasks"]), len(window["phases"]), window["files"])
          if window is not None else
          "live plan window: neither plan points at a recorded run")
    return 0


if __name__ == "__main__":
    _output.safe_stdio()
    raise SystemExit(main(sys.argv[1:]))
