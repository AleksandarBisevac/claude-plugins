#!/usr/bin/env python3
"""
set-priority.py -- the writer behind `/audit:task priority`: pin a phase, or unpin it.

Execution order was implicit in the array, so the only way to say "this phase
first" was to MOVE the phase -- a structural edit of the whole file, and in the
sharded layout an edit of the index nobody performs in flight. This writes one
integer instead, under the index lock, and revalidates.

WHAT IT CANNOT DO, WHICH IS THE POINT. A priority re-sorts work that is ALREADY
ready. It never makes an unready task ready and never skips a dependency, so a
pinned phase still waiting on its `blockedBy` is skipped -- and `/audit:status`
says which task ran instead rather than going quiet. `_priority.py` holds that
arithmetic; this file holds the write.

Usage:
  set-priority.py <manifestPath> <phaseId> <tier> [--force]
  set-priority.py <manifestPath> <phaseId> --clear
                  [--project-dir DIR] [--takeover] [--json]
  set-priority.py --selftest

Exit codes:
  0  written (or already the value asked for -- nothing written, and it says so)
  1  refused invalid: the manifest had findings before the write (nothing
     written), or the write would leave it invalid (rolled back byte-for-byte)
  2  usage: unknown phase, a tier that is not a positive integer, a second
     holder of tier 1 without --force, missing manifest, bad args
  3  the index lock is held by a LIVE run (audit-lock's standard message)
  4  the index lock looks abandoned -- rerun with --takeover once a human has
     confirmed (audit-lock's standard message)

Decisions, each mirroring a precedent in this directory rather than inventing one:

  * INDEX-ONLY. The value goes on the index STUB in the sharded layout, never
    into a shard body -- `_manifest_io.INDEX_ONLY_FIELDS` states the three
    reasons. So this writes ONE file, the index, and never a shard: a phase run
    editing its own shard cannot collide with it.

  * ONE RULE, TWO WRITERS. Whether tier 1 is free is asked of
    `_priority.tier_one_holder()`, the same function the panel's write path
    asks. The Policy tab is the precedent: the verdict the UI shows comes from
    the function the hook calls, so the two cannot drift into a write the panel
    promises and the CLI refuses.

  * ADVISORY maxTier. `priority.maxTier` is printed as a note and NOTHING is
    clamped. A clamped value is a file that says one thing and a run that does
    another.

  * LOCK / WRITE / REVALIDATE / ROLL BACK, and the JOURNAL row -- audit-task.py's
    shape, reached through the SAME functions rather than copied. Those four
    pieces moved into `_panel_write` when this command needed them: two writers
    with two rollbacks are two answers, and an entry point loading another entry
    point is the edge `_deps.KNOWN_LAYER_DEBT` exists to keep at zero new ones.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_set_priority.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
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
import _priority              # noqa: E402  (the ONE expression of order, and its rules)
import _panel_write           # noqa: E402  (the byte-shape writer, the validator handle,
#                                            the index lock, the project walk, the
#                                            snapshot/rollback pair and the journal
#                                            module -- reached by identity, so this
#                                            command and audit-task.py cannot drift)

E_INVALID, E_USAGE, E_LIVE, E_STALE = 1, 2, 3, 4

# The config key that decides how high the panel's control counts. Read here only
# to print a note; nothing is clamped to it.
_MAX_TIER_DEFAULT = 9


# --- resolution ------------------------------------------------------------------
def _resolve_project(args, mpath):
    """Which root owns the journal, the lock and the config.

    F-C-1's rule, and the function that answers it is `_panel_write`'s so that
    `audit-task.py` and this command cannot drift: an explicit --project-dir
    wins, otherwise a NAMED manifest derives the project upward from ITSELF.
    There is no env fallback here because the manifest is always named — the
    positional is required, which is what makes the answer unambiguous.
    """
    if args.project_dir:
        return os.path.abspath(args.project_dir)
    return _panel_write.project_of_manifest(mpath)


def _max_tier(config):
    """`priority.maxTier`, or the shipped default. Never clamps anything."""
    block = (config or {}).get("priority")
    val = block.get("maxTier") if isinstance(block, dict) else None
    if isinstance(val, bool) or not isinstance(val, int) or val < 1:
        return _MAX_TIER_DEFAULT
    return val


def _parse_tier(args, out):
    """`{"ok": True, "tier": None or int}`, or `{"ok": False}` after saying why.

    A DICT AND NOT AN EXIT CODE, and the reason is arithmetic: `E_USAGE` is 2 and
    2 is a perfectly good tier, so a function returning "the tier, or the exit
    code" makes `--clear`-less `set-priority.py m P5 2` indistinguishable from a
    refusal. Success and failure need sentinels that cannot collide.
    """
    if args.clear:
        if args.tier is not None:
            out("[set-priority] pass a tier or --clear, not both")
            return {"ok": False}
        return {"ok": True, "tier": None}
    if args.tier is None:
        out("[set-priority] needs a tier (a positive integer) or --clear")
        return {"ok": False}
    try:
        tier = int(args.tier)
    except (TypeError, ValueError):
        out("[set-priority] tier %r is not an integer - a tier is a rank "
            "starting at 1, and priority 1 is the one tier that must be unique"
            % (args.tier,))
        return {"ok": False}
    if tier < 1:
        out("[set-priority] tier %d is not a rank - tiers start at 1, and an "
            "ABSENT priority is how a phase says 'unprioritised' (it then sorts "
            "after every pinned phase, keeping manifest order)" % tier)
        return {"ok": False}
    return {"ok": True, "tier": tier}


# --- the write -------------------------------------------------------------------
def _stub_of(raw_index, phase_id):
    """The index entry for `phase_id` — a stub in the sharded layout, the whole
    phase in the single-file one. `None` when the index does not name it."""
    for entry in (raw_index.get("phases") or []):
        if isinstance(entry, dict) and entry.get("id") == phase_id:
            return entry
    return None


def _apply(raw_index, phase_id, tier):
    """Set or clear `priority` on the index entry. Returns (was, now) or None.

    THE INDEX IS THE ONLY FILE TOUCHED, in both layouts: in the sharded one the
    stub is the index entry, and in the single-file one the index IS the manifest.
    A shard is never rewritten, so this cannot conflict with a phase run.
    """
    stub = _stub_of(raw_index, phase_id)
    if stub is None:
        return None
    was = stub.get(_priority.FIELD)
    if tier is None:
        stub.pop(_priority.FIELD, None)
        return (was, None)
    stub[_priority.FIELD] = tier
    return (was, tier)


def _journal_row(project, config, mpath, phase_id, was, now):
    """One `phase.priority` row -- audit-task.py's shape and its fail-soft
    contract: a write that HAPPENED must never be reported as failed because the
    record of it could not be."""
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    summary = "%s priority %s -> %s" % (
        phase_id, "none" if was is None else was,
        "none" if now is None else now)
    cfg = None if config else {"manifestPath": os.path.relpath(mpath, project)}
    try:
        ok = bool(mod.append(project, {
            "action": "phase.priority",
            # Persisted row: "/" separators regardless of platform, like every
            # other journal path.
            "target": os.path.relpath(mpath, project).replace(os.sep, "/"),
            "summary": summary,
            "details": {"phaseId": phase_id, "from": was, "to": now},
            "actor": {"author": _panel_write._viewer(project,
                                                     config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


def _locked_set(args, project, config, mpath, phase_id, tier, out):
    """Everything between acquire and release: read, check the rule, write,
    validate-from-disk, roll back on findings, journal, report."""
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[set-priority] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    if not isinstance(assembled, dict) or not isinstance(raw_index, dict):
        out("[set-priority] manifest root is not an object")
        return E_USAGE

    vm = _panel_write._cores()[0]
    pre_findings, _pre_w = vm.validate(assembled)
    if pre_findings:
        # Refusing BEFORE the write is what tells "your change broke it" apart
        # from "it was broken when you arrived".
        out("[set-priority] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    phases = [p for p in (assembled.get("phases") or []) if isinstance(p, dict)]
    target = None
    for ph in phases:
        if ph.get("id") == phase_id:
            target = ph
            break
    if target is None:
        out("[set-priority] no phase %s in the manifest; phases: %s"
            % (phase_id, ", ".join(str(p.get("id")) for p in phases) or "(none)"))
        return E_USAGE

    # THE RULE, ASKED OF THE FUNCTION THE PANEL ALSO ASKS. A refusal that named no
    # holder would leave the reader to grep for it, which is how a refusal becomes
    # a thing people work around instead of resolving.
    if tier == _priority.UNIQUE_TIER and not args.force:
        holder = _priority.tier_one_holder(phases)
        if holder is not None and holder != phase_id:
            out("[set-priority] REFUSED: %s already holds priority %d, and that "
                "is the one tier that must be unique. Clear it first "
                "(set-priority.py <manifest> %s --clear), pin %s to another "
                "tier, or pass --force to write a second holder -- in which "
                "case whichever comes FIRST in the manifest wins, because that "
                "is the tie-break."
                % (holder, _priority.UNIQUE_TIER, holder, phase_id))
            return E_USAGE

    applied = _apply(raw_index, phase_id, tier)
    if applied is None:
        # The assembled manifest names the phase and the index does not: a
        # mixed/hand-edited layout. Saying which file is missing it beats writing
        # a value into a document nobody reads back.
        out("[set-priority] phase %s is not in the index at %s -- priority is an "
            "INDEX-ONLY field, so there is nowhere here to write it"
            % (phase_id, os.path.relpath(mpath, project)))
        return E_USAGE
    was, now = applied
    if was == now:
        out("[set-priority] %s is already %s -- nothing written"
            % (phase_id, "unprioritised" if now is None else "priority %d" % now))
        return 0

    snap = _panel_write.snapshot([mpath])
    try:
        _panel_write._atomic_write_json(mpath, raw_index)
    except Exception as exc:
        _panel_write.restore(snap)
        out("[set-priority] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    # Re-read from DISK, never from the dict just mutated: the point of the check
    # is that what LANDED validates, and a caller who trusted the in-memory copy
    # would be grading the intention rather than the file.
    written_manifest = {}
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _panel_write.restore(snap)
        out("[set-priority] REFUSED: the change would leave the manifest invalid "
            "-- the manifest was rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_row(project, config, mpath, phase_id, was, now)
    written = [os.path.relpath(mpath, project)]
    # ADVISORY, and computed from the manifest as it now stands rather than from
    # the tier alone -- a note about a value nothing clamps has to name the value
    # that made it true.
    over = _priority.over_max(
        [p for p in (written_manifest.get("phases") or [])
         if isinstance(p, dict)], _max_tier(config))
    if args.as_json:
        result = {"ok": True, "phase": phase_id, "from": was, "to": now,
                  "written": written, "warnings": warnings,
                  "overMaxTier": [{"phaseId": pid, "tier": t} for pid, t in over],
                  "maxTier": _max_tier(config)}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[set-priority] %s priority %s -> %s"
        % (phase_id, "none" if was is None else was,
           "none" if now is None else now))
    for pid, t in over:
        out("  note: %s is pinned at %d, above priority.maxTier %d -- nothing is "
            "clamped, it simply sorts after every tier at or under the maximum"
            % (pid, t, _max_tier(config)))
    for line in warnings:
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the phase.priority row")
    out("  written: %s" % ", ".join(written))
    return 0


def cmd_set(args, out):
    if not args.manifest:
        out("[set-priority] needs a manifest path")
        return E_USAGE
    mpath = os.path.abspath(args.manifest)
    if not os.path.isfile(mpath):
        out("[set-priority] manifest not found: %s -- run /audit:init first"
            % mpath)
        return E_USAGE
    phase_id = (args.phase_id or "").strip()
    if not phase_id:
        out("[set-priority] needs a phase id")
        return E_USAGE
    parsed = _parse_tier(args, out)
    if not parsed["ok"]:
        return E_USAGE
    tier = parsed["tier"]
    project = _resolve_project(args, mpath)
    if not os.path.isdir(project):
        out("[set-priority] not a directory: %s" % project)
        return E_USAGE
    config = _panel_write.read_config(project)
    # The lock comes BEFORE the read: the whole read-check-write is serialized, so
    # two sessions cannot both find tier 1 free.
    lock = _panel_write.acquire_index_lock(project, config, mpath,
                                          args.takeover, out,
                                          "[set-priority]", "set priority")
    if isinstance(lock, int):
        return lock
    try:
        return _locked_set(args, project, config, mpath, phase_id, tier, out)
    finally:
        _panel_write.release_index_lock(lock)


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="set-priority.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("phase_id")
    p.add_argument("tier", nargs="?", default=None)
    p.add_argument("--clear", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        return cmd_set(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[set-priority] internal error: %s" % exc)
        return E_INVALID


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would read the flag
        # as a missing positional. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("set-priority.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_set_priority.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
