#!/usr/bin/env python3
"""
The ADO connector's OPERATIONAL half — what a shape-checker cannot see.

Split out of `audit-doctor.py`. The SHAPE of `meta.ado` belongs to
`_manifest_ado.check_ado_meta`, and it reaches the doctor's report through
`check_manifest`; nothing here re-derives it. What is left is the four
questions only a live machine can answer: is the transport installed, which
switches are actually in effect, do the shipped state defaults aim at a process
this project may not use, and what do the manifest's links prove.

Offline on purpose - a doctor that phoned ADO would be a doctor that needs
credentials - which is why the state-map row says "advisory" out loud: real
states live in ADO.

Layer 3: it reads `_doctor_report` (layer 2) for the collector and `_ado_drift`
(layer 2) for the link walk, and reaches nothing else. The walk used to be a
second copy here - including the `id: true` trap - and one walk is why the
doctor's count and the sync command's table cannot disagree about what is linked.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__doctor_ado.py` - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import shutil
import subprocess
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

import _doctor_report as _base  # noqa: E402  (Report, the loader, the constants)
import _ado_drift as _drift  # noqa: E402  (the one link walk, and origins)

# A thin module-level alias, not a copy: the body below was moved out of
# `audit-doctor.py` unchanged, and an alias keeps it reading the same name
# while there is still exactly one definition of it. A case pins the identity.
_load = _base._load


# --- checks: the ADO connector --------------------------------------------------
def check_ado(rep, project, manifest):
    """The ADO connector's OPERATIONAL half (connector v2).

    The SHAPE of meta.ado is the validator's job (check_ado_meta) and reaches
    this report through check_manifest; what a shape-checker cannot see is
    covered here: whether the transport is present, which switches are in
    effect, whether the shipped state defaults aim at a process that may not
    define them, and what the manifest's links actually prove. Offline on
    purpose - a doctor that phoned ADO would be a doctor that needs
    credentials. Real states live in ADO, so the state-map row is exactly
    what it says: advisory."""
    meta = (manifest or {}).get("meta")
    ado = meta.get("ado") if isinstance(meta, dict) else None
    if ado is None:
        rep.ok("ado", "connector not configured (meta.ado absent) - "
               "/audit:sync and the orchestration echo are off")
        return
    if not isinstance(ado, dict):
        return  # a shape defect; check_manifest already carries the finding

    enabled = ado.get("enabled") is not False
    echo = enabled and ado.get("echo") is not False
    pbi = ado.get("phaseWorkItems") is not False
    sprint = ado.get("sprint") if isinstance(ado.get("sprint"), dict) else None
    if not enabled:
        rep.warn("ado",
                 "connector DISABLED (meta.ado.enabled: false) - push/pull "
                 "and the echo do nothing; links are kept and /audit:sync "
                 "status still reports them",
                 "re-enable in the panel's ADO card, or delete the key")
    else:
        pbi_note = ""
        if pbi and not (ado.get("types") or {}).get("pbi"):
            pbi_note = " (types.pbi auto-detected at the first phase push)"
        rep.ok("ado",
               "connector on (org %s, project %s) - echo %s, PBI-per-phase "
               "%s%s, sprint %s"
               % (ado.get("organization") or "?", ado.get("project") or "?",
                  "on" if echo else "off", "on" if pbi else "off", pbi_note,
                  ("resolves team %r" % sprint.get("team")) if sprint
                  else "static (iterationPath)"))

    # Transport: what a headless / CLI run stands on. MCP may still carry an
    # interactive session, which is why a missing az is a warning, never a
    # finding.
    if not shutil.which("az"):
        rep.warn("ado transport",
                 "az CLI is not on PATH - /audit:sync can still use the ADO "
                 "MCP tools when the session has them, else it stops",
                 "install azure-cli, then: az extension add --name azure-devops")
    else:
        try:
            out = subprocess.run(["az", "extension", "list", "--output",
                                  "json"], capture_output=True, text=True,
                                 timeout=15)
            names = [e.get("name") for e in json.loads(out.stdout or "[]")
                     if isinstance(e, dict)]
            if "azure-devops" in names:
                rep.ok("ado transport", "az + azure-devops extension present")
            else:
                rep.warn("ado transport",
                         "az is on PATH but the azure-devops extension is "
                         "not installed",
                         "az extension add --name azure-devops")
        except Exception as exc:
            rep.warn("ado transport",
                     "az is on PATH but `az extension list` did not answer "
                     "(%s) - transport unverified" % exc)

    # Live-gate F3: both stock processes force-clear Remaining Work at their
    # done state, so a configured write degrades to state-only there. Advisory
    # - the goal ("0 left") is met by the process itself.
    oc = ado.get("onComplete")
    if isinstance(oc, dict) and oc.get("remainingWork", 0) is not None:
        rep.warn("ado remaining work",
                 "onComplete.remainingWork is configured, but stock processes "
                 "(Scrum Done, Agile Closed) force-clear the field at done - "
                 "the write degrades to state-only there, and the process "
                 "empties the field by itself. The key matters only for "
                 "custom processes without the clear rule. Advisory only")

    # The Agile-only truth baked into the shipped defaults (D-7).
    if ado.get("stateMap") is None:
        rep.warn("ado state map",
                 "no meta.ado.stateMap: the built-in defaults name "
                 "Agile-process states (task done > Closed). Scrum tasks use "
                 "To Do/In Progress/Done, so a Scrum project should set the "
                 "map. Advisory only: real states live in ADO",
                 "set meta.ado.stateMap in the panel's ADO card")

    # What the links prove. The WALK is not here: `_ado_drift.link_inventory`
    # owns it, including the int-id shape (`True` would otherwise pass for a
    # work-item id), and this row used to be its second copy. One walk means the
    # doctor's count and the sync command's table cannot disagree about what is
    # linked - which they could, silently, while both looked right.
    inventory = _drift.link_inventory(manifest)
    linked = {"task": 0, "bug": 0, "phase": 0}
    newest = None
    for row in inventory:
        linked[row["kind"]] += 1
        ts = row["link"].get("lastSyncedAt")
        if isinstance(ts, str) and (newest is None or ts > newest):
            newest = ts
    origins = _drift.origin_breakdown(inventory)
    if not sum(linked.values()):
        rep.ok("ado links",
               "no item linked yet - configuration, not evidence; "
               "/audit:sync push writes the first links")
    else:
        # The origin split is here rather than in the sync command because it is
        # answerable OFFLINE - it reads the manifest's own links - and because the
        # `unknown` figure is the one nobody would otherwise see: it counts links
        # written before `origin` existed, and it shrinks only as those items are
        # pushed again. A reader shown just the other two reads them as the whole.
        rep.ok("ado links",
               "%d task(s), %d bug(s), %d phase(s) linked%s - %d created here, "
               "%d imported, %d of unknown origin (link written before the "
               "field existed, or by hand)"
               % (linked["task"], linked["bug"], linked["phase"],
                  (" - newest sync %s" % newest) if newest else "",
                  origins[_drift.ORIGIN_CREATED], origins[_drift.ORIGIN_IMPORTED],
                  origins[_drift.UNKNOWN]))


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
        print("_doctor_ado.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__doctor_ado.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
