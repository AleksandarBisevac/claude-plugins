#!/usr/bin/env python3
"""
The panel's READ side: everything `GET /api/*` answers with, off panel-server.py.

Moved out of panel-server.py (P12.3), and split six ways (U3.1). What is left here
is the part that could not go anywhere else: the journal, the help endpoints, the
report export, and `build_state`, which assembles one payload out of all of them.

WHERE THE REST WENT, and why the split has the shape it has. This module sits at
layer 5, with `_panel_write` (6) and `panel-server`/`audit-task` (7) above it, so
every piece cut out of it had to fit at layer 4 or below and everything THOSE
import at 3 or below:

  * `_panel_paths`        (3) the config/manifest paths, and the three modules the
                              panel reads through -- the floor for all five below
  * `_panel_viewer`       (4) who is driving the panel, and its identity cache
  * `_panel_composition`  (4) the plan as the panel shows it: phases, tasks, bugs,
                              the ADO banner, the areas registry
  * `_panel_policy`       (4) the capability policy, and what it decides today
  * `_panel_runstate`     (4) locks, the on-disk change stamp, the Plan gate card
  * `_panel_usage`        (4) the Usage tab's facts

WHAT MADE THE SPLIT POSSIBLE, since it was blocked on this and not on effort. Two
things had to move, and neither was `_stamp`/`_settled`:

  * `_cores()` was a positional 4-tuple bundling `_manifest_rules` (layer 3) with
    three modules that have nothing to do with it. A shared base holding that tuple
    could only sit at 4 -- leaving no layer for the five modules that read it, and
    forcing an eighth layer that would have recorded a grab-bag accessor rather than
    a dependency. `_panel_paths` therefore exposes `hooks_config()` /
    `config_rules()` / `status_facts()` instead, and `_cores()` below still assembles
    the same tuple in the same order for `_panel_write` and `audit-task`, which read
    it positionally.
  * `_help` and `_panel_discovery` were each sitting ONE LAYER ABOVE what their own
    edges require (measured: `_help` reaches nothing above layer 1, `_panel_discovery`
    nothing above `_help`). At 3 and 4 they made `discover` unreachable from a layer-4
    module, which is what `_panel_policy` needs. They now sit at 2 and 3, which is
    where the graph always put them.

panel-server.py and _panel_write.py keep a thin module-level alias for every name
that has ever lived here, so their HTTP routes, the write path and every case that
spells one keep referring to them unchanged. The re-export block below is the other
half of that promise: a name that moved into one of the six modules is bound here
too, so `_panel_state.<name>` still resolves.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__panel_state.py` - see `plugins/audit/tests/_harness.py`.
The `--name-only` SECURITY case moved with `_git_config_origins` and now slices
`_panel_viewer.py` from `tests/test__panel_viewer.py`.

BOUNDARY DECISIONS -- read-side code that touched names the write path also uses:

  * `_JOURNAL` / `_journalmod`. The journal WRITER (`_journal`) stays in
    panel-server (P12.4), but `journal_state` needs the same module handle, so the
    loader and its one-shot memo live here and are aliased back. The alias is the
    same dict object, so the cases on both sides that swap a stub module in by
    mutating `_JOURNAL` in place still reach one shared piece of state.

  * `render_report` STAYS HERE rather than moving with the Usage tab, and that is
    deliberate: it runtime-loads `render-report.py` at layer 7, the edge
    `_deps.KNOWN_LAYER_DEBT` records against this file. Moving it into a
    layer-4 module would have made that recorded edge span three layers instead
    of one while changing nothing about it.

    `report_paths` is NO LONGER part of that edge, and the difference is the
    lesson. It reached the same layer-7 module for `_report_basename` — a pure
    naming rule that `_report_html` owns at layer 2 and `render-report.py` merely
    aliases — so one of the two call sites under that entry was a module being
    used as a LIBRARY through a COMMAND, which is the shape every retired entry
    in that table had. It now imports `_report_html` directly. What is left is
    the half with no downward home: `render_report` wants the WHOLE pipeline
    ending in files on disk, and that pipeline bottoms out at `_report_page`
    (layer 6), above this module's layer 5. See the entry itself for why moving
    this module up, or inverting the call, both relocate the edge rather than
    retire it.

Stdlib only, Python 3.8 compatible.
"""
import contextlib
import io
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

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_rules        # noqa: E402  (the manifest rules, at layer 3 - imported, not loaded)
import _journal_io            # noqa: E402  (read/verify the audit trail, at layer 1)
import _help                  # noqa: E402  (schema-sourced field help + concept topics)
import _panel_discovery       # noqa: E402  (skills/agents/MCP registry scan)
import _panel_paths as _paths          # noqa: E402  (paths + the three cores, at layer 3)
import _panel_viewer as _viewer_mod    # noqa: E402  (who is driving the panel, at layer 4)
import _panel_composition as _composition  # noqa: E402  (the plan as shown, at layer 4)
import _panel_policy as _policy_mod    # noqa: E402  (the capability policy, at layer 4)
import _panel_runstate as _runstate    # noqa: E402  (locks, stamp, gate, at layer 4)
import _panel_usage as _usage          # noqa: E402  (the Usage tab's facts, at layer 4)
import _proposals                      # noqa: E402  (proposals, rule AND read side, at layer 4)
import _report_html                    # noqa: E402  (the report's naming rule, at layer 2)

discover = _panel_discovery.discover
CONFIG_REL = _paths.CONFIG_REL

# --- the names that moved, re-bound so every caller keeps working ----------------
# `panel-server` aliases 35 names off this module and `_panel_write` 14 of them;
# `tests/test__panel_state.py` checks all 35 by name, both that panel-server
# aliases each one AND that it resolves here. A re-export is what makes the
# split invisible to every one of those call sites.

_load = _paths._load
_defaults = _paths._defaults
_within = _paths._within
_config_path = _paths._config_path
_declared_as_of = _paths._declared_as_of
_manifest_path = _paths._manifest_path
_read_json = _paths._read_json
read_config = _paths.read_config

_VIEWER_CACHE = _viewer_mod._VIEWER_CACHE
_IDENTITY_ENV = _viewer_mod._IDENTITY_ENV
_identity_env = _viewer_mod._identity_env
_git_config_origins = _viewer_mod._git_config_origins
_git_config_candidates = _viewer_mod._git_config_candidates
_resolve_viewer = _viewer_mod._resolve_viewer
_viewer = _viewer_mod._viewer

_areas_of = _composition._areas_of
_bugs_view = _composition._bugs_view
_skills_of = _composition._skills_of
_ado_status = _composition._ado_status
_composition_view = _composition._composition_view
_evidence_view = _composition.evidence_view
_empty_evidence = _composition.empty_evidence
areas_state = _composition.areas_state

# NOT `_composition._proposals_view` any more. The Proposals tab and
# `/audit:propose list` render the same array, so the derivation belongs to the
# module that owns proposals rather than to the panel - `_proposals` sits at layer
# 4 like `_panel_composition`, so this module at 5 is the first place both are
# reachable. The name stays bound here, so every caller and case that spells
# `_panel_state._proposals_view` still resolves.
_proposals_view = _proposals.proposal_rows

_policy_rules = _policy_mod._policy_rules
_policy_enforcement = _policy_mod._policy_enforcement
_policy_areas_view = _policy_mod._policy_areas_view
policy_state = _policy_mod.policy_state
_active_area_tags = _policy_mod._active_area_tags

_LOCKDIR_CACHE = _runstate._LOCKDIR_CACHE
_audit_lock_dir = _runstate._audit_lock_dir
_audit_lock_held = _runstate._audit_lock_held
_lockmod = _runstate._lockmod
_lock_info = _runstate._lock_info
data_fingerprint = _runstate.data_fingerprint
_gate_block = _runstate._gate_block
_run_status = _runstate._run_status

_MAX_FACTS = _usage._MAX_FACTS
_FACT_FIELDS = _usage._FACT_FIELDS
_usage_shape = _usage._usage_shape
_ledger_counts = _usage._ledger_counts
_usage_facts = _usage._usage_facts
_usage_manifest_slice = _usage._usage_manifest_slice
_usage_derived = _usage._usage_derived
usage_state = _usage.usage_state


# --- the four cores, still one tuple in one order --------------------------------
def _cores():
    """The manifest rules, validate-config, audit-status and hooks/_config.

    A POSITIONAL 4-TUPLE, KEPT: `_panel_write` (twice) and `audit-task` (twice)
    read index 0 out of it, `_panel_write` and two suites read index 1, and the
    shape is what they read it by. What changed at U3.1 is where the pieces come
    from -- three of them from `_panel_paths` at layer 3, and `_manifest_rules`
    from the plain import above, which is legal HERE at layer 5 and was the one
    thing that could not sit in the shared base.

    There is still exactly one memo, and it is `_panel_paths.hooks_config()`.
    Three of these four were only ever plain module references, which is why
    memoizing them bought nothing and cost the split a layer."""
    return (_manifest_rules, _paths.config_rules(), _paths.status_facts(),
            _paths.hooks_config())


# --- the audit trail ------------------------------------------------------------
_JOURNAL = {"tried": False, "mod": None}


def _journalmod():
    """`_journal_io` — the audit trail, at layer 1.

    THIS IS THE EDGE `_deps` COULD NOT SEE, AND IT IS GONE RATHER THAN HIDDEN.
    It used to spell `script_path("audit-journal.py")` on one line and `load(path)`
    on the next, and the two-step was deliberate: `_runtime_loaded_sibling_names`
    reads only a `.py` literal spelled INSIDE a loader call, so the one-call form
    would have made a `_panel_state -> audit-journal` edge appear and demanded an
    18th `KNOWN_LAYER_DEBT` entry against a list that may only shrink. The comment
    that used to sit here said the edge was real and unrecorded, and it was right.

    A count that a blind spot flatters is not a smaller debt, so the answer was
    never to keep the two-step: it was to make the dependency legal. The trail is
    `_journal_io.py` at layer 1 now, this module is layer 5, and the edge is an
    ordinary downward import that the lint can read and does not have to forgive.

    Still a function returning a module, and callers still handle None: they were
    written when the journal shipped a release later than this call site, and
    "there may be no journal" is a state the panel renders rather than crashes on."""
    if not _JOURNAL["tried"]:
        _JOURNAL["tried"] = True
        _JOURNAL["mod"] = _journal_io
    return _JOURNAL["mod"]

JOURNAL_PAGE = 200


def journal_state(project, limit=JOURNAL_PAGE):
    """`GET /api/journal` — the recent rows, and whether the chain still holds.

    Both halves in one response, because either alone misleads. A list of rows with
    no verdict invites the reader to trust it; a verdict with no rows is a claim
    about something they cannot see. The verdict comes from `audit-journal.verify`
    — the same function the doctor and the CLI call — so the panel cannot develop
    its own opinion about what counts as intact.

    Read-only, and it stays that way: the journal is written by the writers it
    records, never by a request for it.
    """
    out = {"enabled": True, "dir": None, "rows": [], "verify": None,
           "available": False}
    mod = _journalmod()
    if mod is None:
        # This install has no journal module at all (pre-0.29). Reported rather
        # than 404'd: "there is no journal here" is an answer.
        return out
    config = read_config(project)
    out["enabled"] = bool(mod.enabled(config))
    try:
        res = mod.verify(project, config)
        out["available"] = True
        out["verify"] = {k: res[k] for k in
                         ("ok", "exists", "rows", "findings", "warnings")}
        out["dir"] = (_output.posix_rel(res["dir"], project)
                      if _within(project, res["dir"]) else None)
        rows = mod.read_all(project, config)
        out["rows"] = list(reversed(rows[-limit:]))     # newest first
        out["truncated"] = len(rows) > limit
    except Exception as exc:
        out["verify"] = {"ok": False, "exists": False, "rows": 0,
                         "findings": ["could not read the journal: %s" % exc],
                         "warnings": []}
    return out

# --- in-product help ------------------------------------------------------------
def help_state():
    """`GET /api/help` — what every field means, and how the four concepts work.

    Costs nothing to ask and nothing to answer: the field text is EXTRACTED from
    the two shipped schemas at request time, so the drawer cannot drift from the
    document a reader is told to trust, and the concept pages derive every
    executable rule from the code that executes it (`_help` states which). The
    conversational half — the `audit:guide` agent — is a card in this payload
    rather than something the panel spawns: a question a static page already
    answers should not silently bill for a model.

    Project-independent, and deliberately so. It takes no `project` argument
    because there is nothing here to scope: the live verdicts are `/api/policy`,
    the live trail is `/api/journal`, and mixing documentation with state would let
    a reader take a worked example for their own repository.
    """
    return _help.payload()


def help_field(path, doc):
    """`GET /api/help?path=usage.pricing.opus.in&doc=config` — one field.

    The drawer holds a path into a DOCUMENT and the help table is keyed by SHAPES,
    and exactly one thing in this product knows how to get from one to the other:
    `_help.entry_for`. Asking it over HTTP costs a localhost round trip and buys
    the guarantee the policy tab already has — the browser is handed an answer, not
    the machinery to compute one, so a second implementation cannot drift into
    disagreeing with the first.

    `found:false` rather than a 404: "nothing documents this path" is an answer the
    drawer can render, and a 404 would be indistinguishable from a panel talking to
    an install with no help endpoint at all.
    """
    res = _help.entry_for(path, doc)
    if res is None:
        return {"found": False, "path": path, "doc": doc}
    out = dict(res)
    out["found"] = True
    return out

# --- the report export ----------------------------------------------------------
def report_paths(project):
    """(manifest, out_dir, html_path) for this project's report, or None.

    The output location is DERIVED, never taken from the request: there is no path
    parameter to traverse with. Both ends are re-checked against the project root
    anyway, because a manifestPath in config could point outside it."""
    config = read_config(project)
    mpath = _manifest_path(project, config)
    if not (os.path.isfile(mpath) and _within(project, mpath)):
        return None
    out_dir = os.path.dirname(os.path.abspath(mpath))
    if not _within(project, out_dir):
        return None
    # ASKED AT ITS OWNER, NOT AT THE COMMAND THAT RE-EXPORTS IT — see the module
    # docstring for why that retires half of the recorded layer debt. Same
    # function object either way, so the name this returns does not change.
    #
    # THE `except Exception: base = "audit-report"` WENT WITH THE LOADER, because
    # the loader was the only step here that could fail: `load_manifest_safe`
    # documents itself as returning `{}` on ANY error, and `_report_basename` is
    # total over JSON values (it guards `isinstance(meta, dict)` and ends in
    # `or "audit-report"`). A fallback that can no longer fire is not a safety
    # net, it is a defaulted answer waiting to be believed — and this one had
    # been believed once already: `_report_basename` takes META, not the
    # manifest, so handed the whole manifest it found no such key and answered
    # "audit-report" anyway. Every project that sets meta.reportBasename (the
    # shipped example does) rendered its report correctly and then looked for it
    # under the wrong name — "wrote 2 files" followed by a 404. The default is
    # what made that silent, which is the house rule exactly: never fall back to
    # a default to fill a gap. `rb1`/`rb2` in tests/test__panel_state.py are the
    # cases that would have caught it; nothing here could tell the two apart.
    manifest = _mio.load_manifest_safe(mpath)
    base = _report_html._report_basename(manifest.get("meta"), None)
    return mpath, out_dir, os.path.join(out_dir, base + ".html")


def render_report(project):
    """Write the standalone HTML report (and its Markdown twin) for this project.

    Calls render-report.py's own `main` rather than shelling out: same code path
    the CLI takes, no interpreter discovery, and it works the same on Windows."""
    paths = report_paths(project)
    if not paths:
        return {"ok": False,
                "findings": ["no manifest to report on (or its path escapes the "
                             "project) — run /audit:init first"]}
    mpath, out_dir, html_path = paths
    try:
        rr = _load("audit_render_report", "render-report.py")
    except Exception as exc:
        return {"ok": False, "findings": ["cannot load the renderer: %s" % exc]}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = rr.main([mpath, "--out-dir", out_dir, "--format", "both"])
    except Exception as exc:
        return {"ok": False, "findings": ["render failed: %s" % exc]}
    if code != 0:
        return {"ok": False,
                "findings": ["renderer exited %s — run /audit:report for detail"
                             % code]}
    written = [ln[len("wrote "):] for ln in buf.getvalue().splitlines()
               if ln.startswith("wrote ")]
    return {"ok": True, "files": written,
            # Served back through this origin: a browser will not follow a file://
            # link from an http:// page, so handing over a filesystem path would
            # produce a button that silently does nothing.
            "href": "/report", "exists": os.path.isfile(html_path)}

# --- the whole of /api/state ----------------------------------------------------
def build_state(project):
    vm, vc, as_, _ = _cores()
    config = read_config(project)
    cfg_findings, cfg_warnings = vc.validate_config(config)
    mpath = _manifest_path(project, config)
    manifest, exists = None, os.path.isfile(mpath)
    rollup, m_findings = None, []
    composition = {"meta": {"reviewSkill": None, "buildCommands": None,
                            "ado": None},
                   "areaSkills": [],
                   "adoStatus": {"configured": False, "enabled": False,
                                 "echo": False,
                                 "linked": {"tasks": 0, "bugs": 0,
                                            "phases": 0},
                                 "lastSyncedAt": None},
                   "phases": [], "tasks": []}
    # THE EMPTY SHAPE COMES FROM ONE FUNCTION, never a second dict literal here:
    # `evidence` is read only where a pointer exists, so a key spelled in one of
    # these branches and forgotten in the other would be an `undefined` that only
    # a project with no plan ever meets.
    evidence = _empty_evidence()
    proposals = []
    bugs = []
    if exists:
        try:
            manifest = _mio.load_manifest(mpath)   # dual-format: single-file OR index+shards
        except Exception as exc:
            m_findings = ["cannot parse manifest: %s" % exc]
        if isinstance(manifest, dict):
            m_findings, m_warn = vm.validate(manifest)
            rollup = as_.rollup(manifest, m_findings, m_warn)
            composition = _composition_view(manifest)
            # AFTER the composition and off its rows, not off the manifest: the
            # pointers are already on those rows, and the runs worth shipping are
            # exactly the ones they name.
            evidence = _evidence_view(project, composition, config=config)
            bugs = _bugs_view(manifest)
            proposals = _proposals_view(manifest)
    return {
        "project": project,
        "manifestPath": _output.posix_rel(mpath, project),
        "manifestExists": exists,
        "manifestLocked": _audit_lock_held(project, config),
        "viewer": _viewer(project, config),
        "config": config,
        "defaults": _defaults(),
        "configFindings": cfg_findings,
        "configWarnings": cfg_warnings,
        "manifestFindings": m_findings,
        "composition": composition,
        "evidence": evidence,
        "proposals": proposals,
        "bugs": bugs,
        "rollup": rollup,
        "runStatus": _run_status(project, config, manifest),
    }


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_state.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_state.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
