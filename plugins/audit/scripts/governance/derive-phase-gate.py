#!/usr/bin/env python3
"""
derive-phase-gate.py -- observe, derive, record: a PHASE's sign-off gate,
computed rather than declared, beside the wide gate in shadow and as the gate
itself in enforce.

`_gate_derive.derive()` is PURE: every observation it needs arrives through a
`facts` dict, and it never shells out or reads git. This is the one caller that
gathers those observations for real -- the version answer a recorded importer
listing was verified against, the listing itself (run twice: once over every
suite file the runner would collect, once over only this phase's own touched
files), which paths changed since the phase's `baseRef`, the newest RED
phase-scope evidence row, and the plan gate's own exempt verdict per touched
file -- and hands the result to `derive()` unchanged. The runner never derives;
it only measures what the phase declares.

`meta.phaseGate.derived.runner` names a `meta.buildCommands` key: run alone
(through `meta.buildCommands`, `meta.nodePreamble` applied exactly the way
`run-test-gate._resolved` applies it), it is the FULL listing -- every suite
file the runner would collect. `meta.phaseGate.derived.spelling` is a separate
RAW template carrying a `{paths}` placeholder: filled with the shell-quoted
union of the phase's own tasks' `files` (never a buildCommands key -- a phase's
tasks are not one of those), it is the RELATED listing. Both listings write one
line of output per path and never execute a test -- a listing that ran a suite
would make derivation as expensive as the thing it exists to narrow.

WRITE, under the index lock, snapshot before, `_manifest_rules` validate after,
roll back byte for byte on a finding -- the same four-step shape
`set-priority.py` and `audit-task.py` already hold, reached through
`_panel_write` rather than copied: `mode == "shadow"` writes `testGateDerived`
and `testGateBasis` only, `phase.testGate` untouched, because the WIDE gate is
still what signs a shadow-mode phase off; `mode == "enforce"` writes all three.
NONE of the three fields is a `_manifest_io._STUB_KEYS` mirror (`id`, `title`,
`status`), so the write touches only the phase's own shard in the sharded
layout (or the one file, in the single-file layout) and never the index.

`meta.phaseGate.mode` ABSENT means no derivation was ever asked for: this
prints why and writes nothing, exit 0, before a single subprocess runs -- an
operator who has not wired `derived.runner`/`.spelling`/`.verifiedOn` yet pays
nothing for a listing that would tell them nothing.

`derived-empty` (`_manifest_vocab.PHASE_GATE_BASIS[1]`) IS NOT REACHABLE FROM
THIS RUNNER EITHER, and that is not an oversight -- see `_gate_derive.derive`'s
own docstring for why the ONE shape source it knows (`path_scoped_sibling`, a
sibling task's own path-scoped gate) can never return an empty `test_paths`
once a shape exists at all. This runner introduces no ALTERNATE shape source
(the docstring names `meta.phaseGate.derived.runner`/`.spelling` becoming one
on their own, independent of any task -- which is exactly what this file reads
them as an ADDITIONAL arm alongside `path_scoped_sibling`, never a replacement
for it), so the same argument holds here: `shape is None` is still the only way
this phase has nothing to narrow to, and that is reported as `phase-no-spelling`
(already in `derive()`'s own vocabulary), not as `derived-empty`. The word stays
reserved for a caller whose shape source can legitimately return zero paths with
no task's own gate backing it, which this one is not.

Usage:
  derive-phase-gate.py <manifestPath> <phaseId> [--dry-run] [--brief] [--json]
                       [--project-dir DIR] [--takeover]
  derive-phase-gate.py --selftest

Exit codes:
  0  computed (and written, unless --dry-run) -- or nothing to derive, said why
  1  refused invalid: the manifest had findings before the write, or the write
     would leave it invalid (rolled back byte for byte)
  2  usage: unknown phase/manifest, bad args
  3  the index lock is held by a LIVE run
  4  the index lock looks abandoned -- rerun with --takeover once a human has
     confirmed

This module carries no inline `--selftest` of its own; its cases live in
`plugins/audit/tests/test_derive_phase_gate.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time

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

import _evidence_io                  # noqa: E402  (read_rows, subject_key -- the
#                                       newest red phase-scope row)
import _gate_derive                  # noqa: E402  (derive(): the one PURE
#                                       computation; the arm helpers this file
#                                       reuses to REPORT the breakdown derive()
#                                       itself does not expose)
import _loader                       # noqa: E402  (load_hooks_config: the plan
#                                       gate's own exempt-glob answer, asked
#                                       through the one door scripts/ has into
#                                       hooks/)
import _manifest_io as _mio          # noqa: E402  (dual-format loader; index
#                                       lock write target resolution)
import _manifest_phases as _phases   # noqa: E402  (PHASE_GATE_MODES, is_suite_path)
import _panel_write                  # noqa: E402  (the byte-shape writer, the
#                                       validator handle, the index lock, the
#                                       snapshot/rollback pair and the journal
#                                       module -- reached by identity, so this
#                                       command and audit-task.py cannot drift)
import _proc_group                   # noqa: E402  (one child tree stopped
#                                       whole, so a runaway listing cannot
#                                       outlive its own timeout)

E_OK, E_INVALID, E_USAGE, E_LIVE, E_STALE = 0, 1, 2, 3, 4

# How long a single observation may run before it is torn down. A listing never
# executes a test, so these budgets are for a command that hangs (a port it
# cannot bind, a network call with no timeout of its own) rather than for a
# real test suite's own duration.
VERSION_TIMEOUT_SECONDS = 30
LISTING_TIMEOUT_SECONDS = 120
GIT_TIMEOUT_SECONDS = 30


# --- running one observation ----------------------------------------------------
def _with_preamble(command, preamble):
    """`command`, prefixed by `meta.nodePreamble` -- `run-test-gate._resolved`'s
    own join, restated here rather than imported: that function resolves a
    GATE entry through `meta.buildCommands` in the same breath, which is a
    question this file never asks of a listing command at all."""
    lead = (preamble or "").strip() if isinstance(preamble, str) else ""
    return ("%s && %s" % (lead, command)) if lead else command


def _spawn(command, cwd, timeout):
    """`{"exit", "output", "durationMs", "timedOut"}` for one shell command,
    run through `_proc_group` so a child that hangs is torn down WHOLE rather
    than leaving a grandchild running past this process's own patience."""
    start = time.time()
    try:
        proc = subprocess.Popen(["/bin/sh", "-c", command], cwd=cwd,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                **_proc_group.group_kwargs())
    except Exception as exc:
        return {"exit": None, "output": "", "durationMs": 0, "timedOut": False,
                "error": str(exc)}
    try:
        out, _err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _proc_group.tear_down(proc)
        out = _proc_group.drain(proc).encode("utf-8", "replace")
        timed_out = True
    duration_ms = int((time.time() - start) * 1000)
    text = out.decode("utf-8", "replace") if isinstance(out, bytes) else (out or "")
    return {"exit": None if timed_out else proc.returncode, "output": text,
            "durationMs": duration_ms, "timedOut": timed_out}


def _lines_of(text):
    """One path per non-blank line -- the one listing-output convention this
    file reads, for both the version answer's cousin and the two listings."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


# --- gathering the observations `_gate_derive.derive` needs ----------------------
def _named_failing_suites(row):
    """Every suite file the newest red phase-scope ROW named as failing, in
    the order its failed steps carry them, deduplicated.

    THE SAME READING `audit-task._named_failing_suites` HOLDS, restated here:
    two entry points, neither importing the other, asking the identical
    question of the identical row shape. A step counts as failed the same way
    `run-test-gate.failed_steps` reads one (a non-zero exit, no no-verdict
    `outcome`), and ONLY a `failingSuitesBasis` that says the runner named
    them counts -- a capped tail of raw output is not a list of failing
    suites, and learning suites off it would point a derived gate at whatever
    lines happened to scroll past last.
    """
    suites = []
    for step in (row.get("steps") or []) if isinstance(row, dict) else []:
        if not isinstance(step, dict):
            continue
        if step.get("exit") in (0, None) or step.get("outcome"):
            continue
        if "named as failing" not in (step.get("failingSuitesBasis") or ""):
            continue
        for path in step.get("failingSuites") or []:
            if path not in suites:
                suites.append(path)
    return suites


def _touched_paths(phase):
    return _gate_derive._touched_files(phase)


def _gather_facts(manifest, phase, project, out):
    """`(facts, lines)` -- every observation `_gate_derive.derive` may read,
    each measured live and NEVER guessed. `lines` carries a reason for every
    observation this run could not make (no `derived` config at all, no
    `baseRef` to diff from), the same "never silent, never invented" rule
    `_gate_derive._importers_arm` already applies to its own three checks.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived_cfg = gate.get("derived")
    derived_cfg = derived_cfg if isinstance(derived_cfg, dict) else None
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else {}
    preamble = meta.get("nodePreamble")

    facts, lines = {}, []
    if derived_cfg is None:
        lines.append("importers: skipped - meta.phaseGate.derived is not set, "
                     "so there is no listing to run")
        derived_cfg = {}

    verified_on = derived_cfg.get("verifiedOn")
    verified_on = verified_on if isinstance(verified_on, dict) else {}
    version_cmd = verified_on.get("command")
    if isinstance(version_cmd, str) and version_cmd.strip():
        res = _spawn(_with_preamble(version_cmd, preamble), project,
                     VERSION_TIMEOUT_SECONDS)
        facts["versionAnswer"] = res["output"].strip() if res["exit"] == 0 else None

    runner_key = derived_cfg.get("runner")
    spelling = derived_cfg.get("spelling")
    have_runner = isinstance(runner_key, str) and runner_key.strip()
    have_spelling = isinstance(spelling, str) and "{paths}" in spelling
    if have_runner and have_spelling:
        full_cmd = _with_preamble(build.get(runner_key, runner_key), preamble)
        full_res = _spawn(full_cmd, project, LISTING_TIMEOUT_SECONDS)
        facts["fullListing"] = {"exit": full_res["exit"],
                                "paths": _lines_of(full_res["output"])}
        touched = _touched_paths(phase)
        quoted = " ".join(shlex.quote(p) for p in touched)
        related_cmd = _with_preamble(spelling.replace("{paths}", quoted), preamble)
        related_res = _spawn(related_cmd, project, LISTING_TIMEOUT_SECONDS)
        facts["listing"] = {"command": related_cmd, "exit": related_res["exit"],
                            "paths": _lines_of(related_res["output"]),
                            "durationMs": related_res["durationMs"]}
    elif derived_cfg:
        lines.append("importers: skipped - meta.phaseGate.derived carries no "
                     "usable runner/spelling pair")

    base_ref = phase.get("baseRef") if isinstance(phase, dict) else None
    if isinstance(base_ref, str) and base_ref.strip():
        diff_cmd = "git diff --name-only %s...HEAD" % shlex.quote(base_ref)
        diff_res = _spawn(diff_cmd, project, GIT_TIMEOUT_SECONDS)
        if diff_res["exit"] == 0:
            facts["changedSince"] = _lines_of(diff_res["output"])
        else:
            lines.append("changed: skipped - %r exited %r"
                         % (diff_cmd, diff_res["exit"]))
    else:
        lines.append("changed: skipped - phase.baseRef is not set")

    rows = _evidence_io.read_rows(project).get("rows") or []
    red_row = _gate_derive.newest_red_phase_row(rows, phase.get("id")
                                                if isinstance(phase, dict) else None)
    facts["lastFailedSuites"] = _named_failing_suites(red_row) if red_row else []

    hooks_config = _loader.load_hooks_config()
    hcfg = hooks_config.load(project)
    globs = hcfg.get("exemptGlobs") or hooks_config.DEFAULTS.get("exemptGlobs") or []
    facts["exempt"] = dict((p, hooks_config.matches_exempt(p, globs))
                          for p in _touched_paths(phase))
    return facts, lines


# --- the breakdown `derive()` computes but does not expose -----------------------
def _breakdown(manifest, phase, facts):
    """Which ARM contributed which path, for the human line and `testGateDerived`
    -- `None` when there is no path-scoped sibling to repoint at all
    (`phase-no-spelling`), the same question `derive()` itself asks first.

    NOT A SECOND DERIVATION. Every path this returns comes from calling
    `_gate_derive`'s own arm functions in the SAME order `derive()` applies
    them, so the two can disagree only if one of them is edited without the
    other -- and `derive()`'s `entries` stays the one number this file ever
    signs off on; this is reporting, not a rival computation of the gate
    itself.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    shape, _owner = _gate_derive.path_scoped_sibling(phase, build)
    if shape is None:
        return None
    touched = _gate_derive._touched_files(phase)
    tests_add = _gate_derive._tests_add_arm(phase, build)
    running = list(tests_add)
    coupling_new = []
    for path in _gate_derive._coupling_arm(meta, touched):
        if path not in running:
            coupling_new.append(path)
            running.append(path)
    importer_paths, full_suite, _note = _gate_derive._importers_arm(meta, facts)
    importer_new = []
    if not full_suite:
        for path in importer_paths:
            if path not in running:
                importer_new.append(path)
                running.append(path)
    changed_new = []
    for path in (facts.get("changedSince") or []):
        if (isinstance(path, str) and _phases.is_suite_path(path)
                and path not in running):
            changed_new.append(path)
            running.append(path)
    last_failed_new = []
    for path in (facts.get("lastFailedSuites") or []):
        if isinstance(path, str) and path not in running:
            last_failed_new.append(path)
            running.append(path)
    return {"testsAdd": tests_add, "coupling": coupling_new,
            "importers": importer_new, "changed": changed_new,
            "lastFailed": last_failed_new, "union": running,
            "fullSuite": full_suite}


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _smoke_line(result):
    for line in result.get("lines") or []:
        if line.startswith("smoke:"):
            return line
    return None


# --- rendering the two shapes `tools/verify.sh --affected` reads -----------------
def _render_lines(phase_id, meta, result, breakdown, facts):
    """The human lines: one `DERIVED sign-off gate for <P>: ...` or `could not
    be bounded` line, plus every advisory `_gate_derive.derive` returned."""
    if breakdown is None:
        return ["DERIVED sign-off gate for %s could not be bounded: no sibling "
                "task in this phase carries a path-scoped gate of its own, so "
                "there is no spelling to repoint at anything narrower. The wide "
                "gate runs (%s). Nothing was narrowed."
                % (phase_id, ", ".join(result["entries"]) or "nothing")]
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    always = [a for a in (gate.get("always") or []) if isinstance(a, str)]
    entry = gate.get("derived", {}).get("runner") if isinstance(
        gate.get("derived"), dict) else None
    entry = entry or "gate"
    listed_count = len((facts.get("listing") or {}).get("paths") or [])
    line = ("DERIVED sign-off gate for %s: always %s | %s over %d test file(s) "
            "[tests.add %d, coupling %d, importers %d of %d listed, changed %d, "
            "last failed %d]"
            % (phase_id, always, entry, len(breakdown["union"]),
               len(breakdown["testsAdd"]), len(breakdown["coupling"]),
               len(breakdown["importers"]), listed_count,
               len(breakdown["changed"]), len(breakdown["lastFailed"])))
    smoke = _smoke_line(result)
    if smoke:
        line += " | %s" % smoke
    elif isinstance(gate.get("smoke"), str) and gate["smoke"].strip():
        line += " | smoke added"
    line += ". Recorded on phase.testGateBasis."
    out = [line]
    for extra in result.get("lines") or []:
        if not extra.startswith("smoke:"):
            out.append("  " + extra)
    return out


def _brief_line(phase_id, meta, result, breakdown, facts, at):
    """The reviewer's ONE-line basis -- never a path, never runner output
    (tk2): every number here is a COUNT, and the only string carried through
    verbatim is `testGateBasis`, which is a fixed vocabulary word."""
    if breakdown is None:
        return ("derived: could not be bounded for %s; basis: %s; derived at %s"
                % (phase_id, result["basis"], at))
    listed = len(breakdown["union"])
    full = len((facts.get("fullListing") or {}).get("paths") or []) or listed
    couplings = len(breakdown["coupling"])
    smoke = _smoke_line(result)
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    if smoke is None:
        smoke = "added" if isinstance(gate.get("smoke"), str) and gate["smoke"].strip() \
            else "n/a"
    return ("derived: %d of %d; couplings: %d; smoke: %s; basis: %s; derived at %s"
            % (listed, full, couplings, smoke, result["basis"], at))


def _testgatederived(meta, result, breakdown, facts, at):
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived_cfg = gate.get("derived")
    derived_cfg = derived_cfg if isinstance(derived_cfg, dict) else {}
    doc = {"narrowed": bool(result["narrowed"]), "at": at}
    if breakdown is not None:
        doc["tests"] = list(breakdown["union"])
        doc["full"] = bool(breakdown["fullSuite"])
        doc["arms"] = {"tests.add": list(breakdown["testsAdd"]),
                       "coupling": list(breakdown["coupling"]),
                       "importers": list(breakdown["importers"]),
                       "changed": list(breakdown["changed"]),
                       "lastFailed": list(breakdown["lastFailed"])}
    if derived_cfg.get("runner"):
        doc["entry"] = derived_cfg["runner"]
    if "listing" in facts:
        doc["listed"] = list(facts["listing"].get("paths") or [])
        doc["listing"] = {"command": facts["listing"].get("command"),
                          "exit": facts["listing"].get("exit"),
                          "durationMs": facts["listing"].get("durationMs")}
    always = [a for a in (gate.get("always") or []) if isinstance(a, str)]
    if always:
        doc["always"] = always
    smoke = gate.get("smoke")
    if isinstance(smoke, str) and smoke.strip():
        doc["smoke"] = smoke
    return doc


# --- the write: reusing the house pattern, never hand-rolled ---------------------
def _shard_path_for(raw_index, mpath, phase_id):
    """The absolute shard path this phase's stub names, or None in the
    single-file layout (or a mixed/hand-edited index that names no shard)."""
    if not _mio.is_sharded(raw_index):
        return None
    base = os.path.dirname(os.path.abspath(mpath))
    for stub in (raw_index.get("phases") or []):
        if isinstance(stub, dict) and stub.get("id") == phase_id \
                and "shard" in stub:
            return os.path.abspath(os.path.join(base, stub["shard"]))
    return None


def _write_targets(mpath, raw_index, phase_id):
    """The files a write MAY touch, for the pre-write snapshot -- the manifest
    itself, plus the phase's own shard in the sharded layout. Mirrors
    `audit-task._write_paths`'s reasoning for the identical reason: an entry
    point may not import another entry point, so the shape is restated here
    rather than reached through one."""
    paths = [mpath]
    spath = _shard_path_for(raw_index, mpath, phase_id)
    if spath:
        paths.append(spath)
    return paths


def _write_phase_fields(project, mpath, raw_index, phase_id, fields):
    """Persist `fields` onto the phase's OWN record and nothing else.

    NONE of `testGate`/`testGateBasis`/`testGateDerived` is a
    `_manifest_io._STUB_KEYS` mirror (`id`, `title`, `status`), so this write
    never touches the index: single-file layout rewrites the one file: sharded
    layout rewrites only the touched phase's shard, which is what keeps a
    derived-gate run from manufacturing a merge conflict in every OTHER
    phase's shard the way rewriting the whole assembled manifest would.
    """
    if not _mio.is_sharded(raw_index):
        assembled = _mio.load_manifest(mpath)
        for ph in (assembled.get("phases") or []):
            if isinstance(ph, dict) and ph.get("id") == phase_id:
                ph.update(fields)
                break
        _panel_write._atomic_write_json(mpath, assembled)
        return [_output.posix_rel(mpath, project)]
    spath = _shard_path_for(raw_index, mpath, phase_id)
    if spath is None:
        raise ValueError("phase %s has no shard on disk to write" % (phase_id,))
    if not _panel_write._within(project, spath):
        raise ValueError("refused: shard path escapes project: %s" % (spath,))
    body = _mio.read_json(spath)
    if not isinstance(body, dict):
        raise ValueError("shard %s is not an object" % (spath,))
    body.update(fields)
    _panel_write._atomic_write_json(spath, body)
    return [_output.posix_rel(spath, project)]


def _journal_row(project, config, mpath, phase_id, mode, changes, basis):
    """One `phase.gateDerived` row -- audit-task.py's fail-soft contract: a
    write that happened must never be reported as failed because the record
    of it could not be."""
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append_from_cli"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    cfg = None if config else {"manifestPath": _output.posix_rel(mpath, project)}
    try:
        ok = bool(mod.append_from_cli(project, {
            "action": "phase.gateDerived",
            "target": _output.posix_rel(mpath, project),
            "summary": "%s gate derived (%s): %s" % (phase_id, mode, basis),
            "details": {"phaseId": phase_id, "mode": mode, "changes": changes,
                       "basis": basis},
            "actor": {"author": _panel_write._viewer(project, config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


# --- the locked run ---------------------------------------------------------------
def _resolve_project(args, mpath):
    if args.project_dir:
        return _panel_write.project_basis(os.path.abspath(args.project_dir),
                                          "--project-dir")
    return _panel_write.project_basis(_panel_write.project_of_manifest(mpath),
                                      "manifest argument")


def _locked_run(args, project, config, mpath, phase_id, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[derive-phase-gate] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    if not isinstance(assembled, dict) or not isinstance(raw_index, dict):
        out("[derive-phase-gate] manifest root is not an object")
        return E_USAGE

    vm = _panel_write._cores()[0]
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[derive-phase-gate] the manifest is already invalid -- nothing "
            "written; fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    phase = None
    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == phase_id:
            phase = ph
            break
    if phase is None:
        out("[derive-phase-gate] no phase %s in this manifest" % (phase_id,))
        return E_USAGE

    meta = assembled.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    mode = gate.get("mode")
    if mode not in _phases.PHASE_GATE_MODES:
        msg = ("meta.phaseGate.mode is not set -- nothing is derived, and "
              "phase.testGate (wide) is the whole answer. Set "
              "meta.phaseGate.mode to 'shadow' or 'enforce' to turn narrowing on.")
        if args.as_json:
            out(json.dumps({"ok": True, "phase": phase_id, "derived": False,
                            "written": [], "why": msg}, indent=2, sort_keys=True))
        else:
            out("[derive-phase-gate] %s: %s" % (phase_id, msg))
        return E_OK

    facts, fact_lines = _gather_facts(assembled, phase, project, out)
    result = _gate_derive.derive(assembled, phase, facts)
    result["lines"] = list(result.get("lines") or []) + fact_lines
    breakdown = _breakdown(assembled, phase, facts)
    at = _now_iso()

    human_lines = _render_lines(phase_id, meta, result, breakdown, facts)
    brief_line = (_brief_line(phase_id, meta, result, breakdown, facts, at)
                 if args.brief else None)
    if not args.as_json:
        for line in human_lines:
            out(line)
        if brief_line:
            out(brief_line)

    if args.dry_run:
        if args.as_json:
            out(json.dumps({"ok": True, "phase": phase_id, "mode": mode,
                            "basis": result["basis"], "narrowed": result["narrowed"],
                            "dryRun": True, "written": [], "lines": human_lines,
                            "brief": brief_line}, indent=2, sort_keys=True))
        return E_OK

    fields = {"testGateDerived": _testgatederived(meta, result, breakdown,
                                                 facts, at),
             "testGateBasis": result["basis"]}
    changes = ["testGateDerived", "testGateBasis"]
    if mode == "enforce":
        fields["testGate"] = list(result["entries"])
        changes.append("testGate")

    snap = _panel_write.snapshot(_write_targets(mpath, raw_index, phase_id))
    try:
        written = _write_phase_fields(project, mpath, raw_index, phase_id, fields)
    except Exception as exc:
        _panel_write.restore(snap)
        out("[derive-phase-gate] write failed -- manifest restored: %s" % exc)
        return E_INVALID

    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, _warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings = ["cannot re-read the written manifest: %s" % exc]
    if findings:
        _panel_write.restore(snap)
        out("[derive-phase-gate] REFUSED: the derived gate would leave the "
            "manifest invalid -- rolled back byte for byte, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_row(project, config, mpath, phase_id, mode, changes,
                        result["basis"])
    if args.as_json:
        out(json.dumps({"ok": True, "phase": phase_id, "mode": mode,
                        "basis": result["basis"], "narrowed": result["narrowed"],
                        "dryRun": False, "written": written, "lines": human_lines,
                        "brief": brief_line, "journaled": jres.get("journaled", False)},
                       indent=2, sort_keys=True))
    else:
        out("  written: %s" % ", ".join(written))
        if not jres.get("journaled"):
            out("  note: not journaled (%s)" % jres.get("journaledWhy"))
    return E_OK


def cmd_derive(args, out):
    if not args.manifest:
        out("[derive-phase-gate] needs a manifest path")
        return E_USAGE
    mpath = os.path.abspath(args.manifest)
    if not os.path.isfile(mpath):
        out("[derive-phase-gate] manifest not found: %s -- run /audit:init first"
            % mpath)
        return E_USAGE
    phase_id = (args.phase_id or "").strip()
    if not phase_id:
        out("[derive-phase-gate] needs a phase id")
        return E_USAGE
    basis = _resolve_project(args, mpath)
    project = basis["root"]
    if not os.path.isdir(project):
        out("[derive-phase-gate] not a directory: %s" % project)
        return E_USAGE
    config = _panel_write.read_config(project)
    lock = _panel_write.acquire_index_lock(project, config, mpath,
                                          args.takeover, out,
                                          "[derive-phase-gate]",
                                          "derive phase gate")
    if isinstance(lock, int):
        return lock
    try:
        return _locked_run(args, project, config, mpath, phase_id, out)
    finally:
        _panel_write.release_index_lock(lock, out=out)


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="derive-phase-gate.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("phase_id")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--brief", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--takeover", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        return cmd_derive(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[derive-phase-gate] internal error: %s" % exc)
        return E_INVALID


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("derive-phase-gate.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_derive_phase_gate.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
