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

`meta.phaseGate.derived.runner` names a `meta.buildCommands` key: the test
runner this phase's gate is stated in terms of, carried through only as a
DISPLAY label (the `entry` this file's own lines and `testGateDerived` name),
never resolved or run for a listing. `meta.phaseGate.derived.spelling` is that
runner's own path-scoped RUN command, carrying a `{paths}` placeholder -- it
is the SECOND source `_gate_derive.resolve_shape` tries for the shape a
narrowed gate repoints, read only when no sibling task's own gate carries a
path-scoped entry (the sibling always wins -- its entry is evidence the
runner already accepted it, `spelling` is not). `{paths}` is filled with the
shell-quoted, resolved test paths by LITERAL substitution, never through
`repointed()` (the placeholder is not a path-shaped token that function would
recognize). The TWO LISTINGS this file actually
runs live under `meta.phaseGate.derived.listing`: `.all` lists every suite
file the runner would collect, with no path filter -- the FULL listing --and
`.related` carries a `{paths}` placeholder, filled with the shell-quoted union
of the phase's own tasks' `files`, for the RELATED listing. Both listings
write one line of output per path and never execute a test -- a listing that
ran a suite would make derivation as expensive as the thing it exists to
narrow -- and both are timed: `fullListing` and `listing` each carry their own
`durationMs`, and `testGateDerived` records both costs.

A `verifiedOn.command` that cannot be run or exits non-zero is its own printed
skip reason ("the version command failed"), kept apart from a machine
answering a DIFFERENT version: rendering the first as "this machine answers
None" would read as an actual mismatched answer rather than as no answer at
all having been produced.

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

`derived-empty` (`_manifest_vocab.PHASE_GATE_BASIS[1]`) IS REACHABLE FROM THIS
RUNNER: `meta.phaseGate.derived.listing.all` is the ADDITIONAL shape source
`_gate_derive.derive`'s own docstring names -- unlike `path_scoped_sibling`'s
own shape (a sibling task's own path-scoped gate, which can never return an
empty `test_paths` once it exists at all), an ALL listing is free to run,
exit 0, and name no suite. When it does, `derive()` widens the WHOLE
derivation to basis `derived-empty` with a printed reason, before coupling,
importers, changed or last-failed ever run -- never an empty result read as
"narrowed to nothing".

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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _evidence_io                  # noqa: E402  (read_rows, subject_key -- the
#                                       newest red phase-scope row; and
#                                       named_failing_suites, its suites)
import _gate_derive                  # noqa: E402  (derive(): the one PURE
#                                       computation, and the ONLY place the
#                                       per-arm attribution renderers read is
#                                       computed -- this file never recomputes
#                                       it)
import _loader                       # noqa: E402  (load_hooks_config: the plan
#                                       gate's own exempt-glob answer, asked
#                                       through the one door scripts/ has into
#                                       hooks/)
import _manifest_io as _mio          # noqa: E402  (dual-format loader; index
#                                       lock write target resolution)
import _manifest_phases as _phases   # noqa: E402  (PHASE_GATE_MODES)
import _manifest_vocab as _vocab     # noqa: E402  (PHASE_GATE_BASIS: the one
#                                       "derived-empty" word, read here rather
#                                       than restated as a literal)
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
    than leaving a grandchild running past this process's own patience.

    The shell and its environment are `_proc_group.shell_invocation`'s: the
    same POSIX `sh` the gate runs a plan command under, with the same PATH, and
    on a machine with none, the refusal naming what to install carried as
    `error` rather than a spawn error that names none."""
    start = time.time()
    argv, env, refusal = _proc_group.shell_invocation(command)
    if argv is None:
        return {"exit": None, "output": "", "durationMs": 0, "timedOut": False,
                "error": refusal}
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env,
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
    preamble = meta.get("nodePreamble")

    facts, lines = {}, []
    # SAID ONCE, AHEAD OF EVERY SKIP IT CAUSES: with no POSIX shell each
    # observation below fails, and each skip line would otherwise read as that
    # command's own failure rather than as the one missing prerequisite.
    _sh, no_sh = _proc_group.resolve_sh()
    if no_sh:
        lines.append("shell: could not run - %s" % (no_sh,))
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
        if res["exit"] == 0:
            facts["versionAnswer"] = res["output"].strip()
        else:
            # ITS OWN SKIP REASON, never folded into "this machine answers
            # None": that would read as an actual (mismatched) answer rather
            # than as no answer at all having been produced.
            facts["versionCheckFailed"] = True

    listing_cfg = derived_cfg.get("listing")
    listing_cfg = listing_cfg if isinstance(listing_cfg, dict) else None
    all_cmd_tpl = listing_cfg.get("all") if listing_cfg else None
    related_tpl = listing_cfg.get("related") if listing_cfg else None
    have_all = isinstance(all_cmd_tpl, str) and all_cmd_tpl.strip()
    have_related = isinstance(related_tpl, str) and "{paths}" in related_tpl
    if have_all and have_related:
        full_cmd = _with_preamble(all_cmd_tpl, preamble)
        full_res = _spawn(full_cmd, project, LISTING_TIMEOUT_SECONDS)
        facts["fullListing"] = {"exit": full_res["exit"],
                                "paths": _lines_of(full_res["output"]),
                                "durationMs": full_res["durationMs"]}
        touched = _touched_paths(phase)
        quoted = " ".join(shlex.quote(p) for p in touched)
        related_cmd = _with_preamble(related_tpl.replace("{paths}", quoted), preamble)
        related_res = _spawn(related_cmd, project, LISTING_TIMEOUT_SECONDS)
        facts["listing"] = {"command": related_cmd, "exit": related_res["exit"],
                            "paths": _lines_of(related_res["output"]),
                            "durationMs": related_res["durationMs"]}
    elif derived_cfg:
        lines.append("importers: skipped - meta.phaseGate.derived.listing "
                     "carries no usable related/all pair")

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
    # The one reading every learner shares: a failed, unmuted step whose
    # runner NAMED its suites - never a tail of output.
    facts["lastFailedSuites"] = (
        _evidence_io.named_failing_suites(red_row.get("steps"))
        if red_row else [])

    hooks_config = _loader.load_hooks_config()
    hcfg = hooks_config.load(project)
    globs = hcfg.get("exemptGlobs") or hooks_config.DEFAULTS.get("exemptGlobs") or []
    facts["exempt"] = dict((p, hooks_config.matches_exempt(p, globs))
                          for p in _touched_paths(phase))
    return facts, lines


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _smoke_line(result):
    for line in result.get("lines") or []:
        if line.startswith("smoke:"):
            return line
    return None


# --- rendering the two shapes `tools/verify.sh --affected` reads -----------------
# BOTH renderers below read ONLY `result` (`_gate_derive.derive()`'s own
# return) and `facts` -- never a second, independently-computed breakdown. A
# second, independent computation of the same arms does not know every
# widening trigger `derive()` knows, so it reports a narrowed-looking
# breakdown for a gate that is actually wide -- which is why `derive()` is
# the only place that computation happens, and why the branch below is keyed
# off `result["narrowed"]` and `result["basis"]` rather than off whether
# `result["attribution"]` happens to be `None`: the two agree by
# construction, but a renderer that keys off the WRONG one of them silently
# stops agreeing the next time a wide trigger is added.
def _render_lines(phase_id, meta, result, facts):
    """The human lines: one `DERIVED sign-off gate for <P>: ...`, `could not
    be bounded` or wide-gate line, plus every advisory `_gate_derive.derive`
    returned."""
    if not result.get("narrowed"):
        basis = result.get("basis")
        if basis == "phase-no-spelling":
            out = ["DERIVED sign-off gate for %s could not be bounded: no "
                  "sibling task in this phase carries a path-scoped gate of "
                  "its own, and meta.phaseGate.derived.spelling names no "
                  "usable {paths} template either, so there is nothing to "
                  "repoint at anything narrower. The wide gate runs (%s). "
                  "Nothing was narrowed."
                  % (phase_id, ", ".join(result["entries"]) or "nothing")]
        else:
            # `derived-empty` (EITHER trigger) and a FULL-SUITE resolution
            # all render the SAME honest wide line, keyed off `narrowed`
            # being False -- never a narrowed-looking count for a gate that
            # is not narrowed. WHICH basis applies, and why, is still named,
            # as the advisory lines below (every `result["lines"]` entry,
            # plus a full-suite resolution's MEASURED listed-of-full count,
            # which comes from `facts`, never from a per-arm breakdown).
            out = ["DERIVED sign-off gate for %s: nothing to narrow to - the "
                  "wide gate runs (%s). Recorded on phase.testGateBasis."
                  % (phase_id, ", ".join(result["entries"]) or "nothing")]
        for extra in result.get("lines") or []:
            out.append("  " + extra)
        if basis == _vocab.PHASE_GATE_BASIS[2]:
            listed_count = len((facts.get("listing") or {}).get("paths") or [])
            full_count = len((facts.get("fullListing") or {}).get("paths") or [])
            out.append("  listed %d of %d (full)" % (listed_count, full_count))
        return out
    attribution = result["attribution"]
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    always = [a for a in (gate.get("always") or []) if isinstance(a, str)]
    entry = gate.get("derived", {}).get("runner") if isinstance(
        gate.get("derived"), dict) else None
    entry = entry or "gate"
    listed_count = len((facts.get("listing") or {}).get("paths") or [])
    line = ("DERIVED sign-off gate for %s: always %s | %s over %d test file(s) "
            "[tests.add %d, coupling %d, importers %d of %d listed, changed %d, "
            "last failed %d] (shape: %s)"
            % (phase_id, always, entry, len(attribution["union"]),
               len(attribution["testsAdd"]), len(attribution["coupling"]),
               len(attribution["importers"]), listed_count,
               len(attribution["changed"]), len(attribution["lastFailed"]),
               result.get("shapeSource") or "n/a"))
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


def _brief_line(phase_id, meta, result, facts, at):
    """The reviewer's ONE-line basis -- never a path, never runner output:
    every number here is a COUNT, and the only string carried through
    verbatim is `testGateBasis`, which is a fixed vocabulary word. Keyed off
    `narrowed`/`basis` the same way `_render_lines` is -- a wide gate never
    prints a per-arm count, MEASURED or otherwise, except the full-suite
    basis's own listed-of-full pair, which comes straight from `facts`."""
    if not result.get("narrowed"):
        basis = result.get("basis")
        if basis == _vocab.PHASE_GATE_BASIS[1]:
            note = "derived-empty"
        elif basis == _vocab.PHASE_GATE_BASIS[2]:
            listed = len((facts.get("listing") or {}).get("paths") or [])
            full = len((facts.get("fullListing") or {}).get("paths") or [])
            return ("derived: full suite (%d of %d); basis: %s; derived at %s"
                    % (listed, full, result["basis"], at))
        else:
            note = "could not be bounded"
        return ("derived: %s for %s; basis: %s; derived at %s"
                % (note, phase_id, result["basis"], at))
    attribution = result["attribution"]
    listed = len(attribution["union"])
    full = len((facts.get("fullListing") or {}).get("paths") or []) or listed
    couplings = len(attribution["coupling"])
    smoke = _smoke_line(result)
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    if smoke is None:
        smoke = "added" if isinstance(gate.get("smoke"), str) and gate["smoke"].strip() \
            else "n/a"
    return ("derived: %d of %d; couplings: %d; smoke: %s; shape: %s; basis: "
            "%s; derived at %s"
            % (listed, full, couplings, smoke,
               result.get("shapeSource") or "n/a", result["basis"], at))


def _testgatederived(meta, result, facts, at):
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived_cfg = gate.get("derived")
    derived_cfg = derived_cfg if isinstance(derived_cfg, dict) else {}
    doc = {"narrowed": bool(result["narrowed"]), "at": at,
          # MEASURED, not derived from a per-arm breakdown: `full` is True
          # exactly when the importer arm resolved to the full suite,
          # regardless of whether `attribution` carries anything -- a wide
          # gate has no `attribution` at all, full-suite included.
          "full": result.get("basis") == _vocab.PHASE_GATE_BASIS[2]}
    attribution = result.get("attribution")
    if attribution is not None:
        doc["tests"] = list(attribution["union"])
        doc["arms"] = {"tests.add": list(attribution["testsAdd"]),
                       "coupling": list(attribution["coupling"]),
                       "importers": list(attribution["importers"]),
                       "changed": list(attribution["changed"]),
                       "lastFailed": list(attribution["lastFailed"])}
        doc["shapeSource"] = result.get("shapeSource")
    if derived_cfg.get("runner"):
        doc["entry"] = derived_cfg["runner"]
    if "listing" in facts:
        doc["listed"] = list(facts["listing"].get("paths") or [])
        doc["listing"] = {"command": facts["listing"].get("command"),
                          "exit": facts["listing"].get("exit"),
                          "durationMs": facts["listing"].get("durationMs")}
    if "fullListing" in facts:
        doc["fullListing"] = {"exit": facts["fullListing"].get("exit"),
                              "durationMs": facts["fullListing"].get("durationMs")}
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
    if mod is None or not hasattr(mod, "append_from_cli_why"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    cfg = None if config else {"manifestPath": _output.posix_rel(mpath, project)}
    try:
        written, why = mod.append_from_cli_why(project, {
            "action": "phase.gateDerived",
            "target": _output.posix_rel(mpath, project),
            "summary": "%s gate derived (%s): %s" % (phase_id, mode, basis),
            "details": {"phaseId": phase_id, "mode": mode, "changes": changes,
                        "basis": basis},
            "actor": {"author": _panel_write._viewer(project, config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg)
    except Exception as exc:
        written, why = False, exc
    return _panel_write.journal_block(project, written, why)


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
    at = _now_iso()

    human_lines = _render_lines(phase_id, meta, result, facts)
    brief_line = (_brief_line(phase_id, meta, result, facts, at)
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

    fields = {"testGateDerived": _testgatederived(meta, result, facts, at),
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
        body = {"ok": True, "phase": phase_id, "mode": mode,
                "basis": result["basis"], "narrowed": result["narrowed"],
                "dryRun": False, "written": written, "lines": human_lines,
                "brief": brief_line, "journaled": jres.get("journaled", False)}
        # A row that did not land says why on this surface too, in the keys
        # every other writer's JSON block already carries.
        body.update((k, jres[k]) for k in ("journaledWhy", "journaledReason")
                    if k in jres)
        out(json.dumps(body, indent=2, sort_keys=True))
    else:
        out("  written: %s" % ", ".join(written))
        if not jres.get("journaled"):
            out("  note: not journaled (%s)" % (jres.get("journaledReason")
                                                 or jres.get("journaledWhy"),))
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
    _claude_home.attach_usage_hint(p)
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
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
