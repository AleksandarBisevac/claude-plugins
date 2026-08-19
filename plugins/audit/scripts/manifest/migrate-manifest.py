#!/usr/bin/env python3
"""
Migrate an audit manifest from the single-file layout to the SHARDED layout
(index + per-phase shards) — dependency-free (stdlib only).

The sharded layout keeps the shared, rarely-churned data (meta, bugs, fileIndex) in the
index and each phase's body in `phases/<phaseId>.json`, so a phase command loads only its
own phase (fewer tokens) and two parallel phase branches edit different files (no manifest
merge conflict). Reading is transparent — every script + hook already loads both layouts
via _manifest_io — so migration is opt-in and the single-file layout stays supported.

It is NOT reversible. Nothing here writes an assembled single file back out — `split_manifest`
has no counterpart — so the only way back is restoring the `.bak-<UTC>` copy, which discards
every manifest write made after the migration. Say that wherever the backup is mentioned: a
backup is a restore point, not an undo.

Usage:
  migrate-manifest.py <manifest> [--dry-run] [--force] [--renumber]
  migrate-manifest.py --selftest

Safe by default:
  - ALREADY sharded  -> nothing to do (exit 0)
  - validates the SOURCE first; refuses to migrate a manifest with findings (exit 1)
    (--renumber first repairs duplicate BUG- ids — the common cross-machine collision)
  - refuses if any phase is `in_progress` (a mid-run migration corrupts the run);
    override with --force
  - backs up the original to <manifest>.bak-<UTC> before writing
  - validates the RESULT; on any failure it RESTORES the backup and exits non-zero

Exit codes: 0 ok / already-sharded · 1 refused or validation failure · 2 usage/unreadable.

This script carries no `--selftest` of its own any more; its 11 cases live in
`plugins/audit/tests/test_migrate_manifest.py` (hyphens become underscores - a
hyphenated name is not importable). It is one of the three pilots of that migration;
see `plugins/audit/tests/_harness.py`.
"""
import datetime
import os
import re
import shutil
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

import _manifest_io as _mio  # noqa: E402
import _manifest_rules  # noqa: E402  (the manifest rules, at layer 2 - imported, not loaded)


# --- migration ------------------------------------------------------------------
def _load_validator():
    """The manifest rules. A plain module now, not a `_loader.load_script` of
    `validate-manifest.py`: that was this file (L7) loading an L7 peer, one of the
    edges `_deps.KNOWN_LAYER_DEBT` recorded, and the rules moved to layer 2 so
    both of us could import the one implementation instead."""
    return _manifest_rules


def _utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _in_progress_phases(manifest):
    return [p.get("id") for p in manifest.get("phases", [])
            if isinstance(p, dict) and p.get("status") == "in_progress"]


def renumber_duplicate_bugs(manifest):
    """Repair duplicate BUG- ids (the common cross-machine collision) by renaming the
    later duplicate to the next free number and fixing its reciprocal task.bugId link.
    Returns [(old, new), ...]. Other duplicate-id classes (phase/task) are left for
    manual repair — auto-renumbering them would have to rewrite dependsOn/blockedBy/
    fileIndex and is too risky to automate blindly."""
    bugs = manifest.get("bugs") or []
    mx = 0
    for b in bugs:
        m = re.match(r"^BUG-(\d+)$", str(b.get("id", "")))
        if m:
            mx = max(mx, int(m.group(1)))
    # The shared index, and the values are the LIVE task dicts (pinned in
    # `_manifest_io`), which is what lets the reciprocal `task.bugId` below be
    # rewritten through it.
    task_by_id = _mio.tasks_by_id(manifest)
    seen, changed = set(), []
    for b in bugs:
        bid = b.get("id")
        if bid in seen:
            mx += 1
            new = "BUG-%d" % mx
            tid = b.get("taskId")
            if tid in task_by_id and task_by_id[tid].get("bugId") == bid:
                task_by_id[tid]["bugId"] = new
            b["id"] = new
            changed.append((bid, new))
        else:
            seen.add(bid)
    return changed


def migrate(path, *, dry_run=False, force=False, renumber=False, out=None):
    """Do the migration. Returns (exit_code, message)."""
    # detect already-sharded from the RAW index (before assembly)
    try:
        raw = _mio._read_json(path)
    except Exception as exc:
        return 2, "cannot read/parse %s: %s" % (path, exc)
    if _mio.is_sharded(raw):
        return 0, "already sharded: %s (nothing to do)" % path
    try:
        manifest = _mio.load_manifest(path)
    except Exception as exc:
        return 2, "cannot load %s: %s" % (path, exc)
    if not isinstance(manifest, dict):
        return 2, "%s is not a JSON object" % path

    vm = _load_validator()
    if renumber:
        changed = renumber_duplicate_bugs(manifest)
        if changed:
            sys.stderr.write("renumbered duplicate bug ids: %s\n"
                             % ", ".join("%s->%s" % c for c in changed))
    findings, _ = vm.validate(manifest)
    if findings:
        return 1, ("source manifest has %d finding(s); fix them before migrating"
                   "%s:\n  - %s" % (len(findings),
                   " (or pass --renumber for duplicate BUG- ids)"
                   if any("duplicate" in f.lower() and "BUG-" in f for f in findings) else "",
                   "\n  - ".join(findings[:8])))

    blocked = _in_progress_phases(manifest)
    if blocked and not force:
        return 1, ("refusing: phase(s) %s are in_progress — migrating mid-run corrupts the "
                   "run. Finish/pause them, or pass --force." % ", ".join(str(b) for b in blocked))

    index, shards = _mio.split_manifest(manifest)
    if dry_run:
        return 0, ("DRY RUN: would write index %s + %d shard(s): %s"
                   % (out or path, len(shards),
                      ", ".join("phases/%s.json" % _mio._shard_name(p) for p in shards)))

    target = out or path
    backup = None
    if out is None:                     # in-place: back up the original first
        backup = "%s.bak-%s" % (path, _utc_stamp())
        shutil.copy2(path, backup)
    try:
        written = _mio.save_sharded(target, manifest)
        # validate the RESULT by reloading through the loader
        result = _mio.load_manifest(target)
        rfindings, _ = vm.validate(result)
        if rfindings:
            raise RuntimeError("post-migration validation failed: %s" % "; ".join(rfindings[:4]))
    except Exception as exc:
        if backup and os.path.exists(backup):
            shutil.copy2(backup, path)   # restore
        return 1, "migration failed (restored backup): %s" % exc

    msg = "migrated %s -> index + %d shard(s)" % (target, len(shards))
    if backup:
        msg += "\n  backup: %s" % backup
    msg += "\n  " + "\n  ".join(written)
    return 0, msg


# --- cli ------------------------------------------------------------------------
def main(argv):
    if "--selftest" in argv:
        # Kept, rather than left to fall through to the usage error below: every
        # other file here still answers `--selftest`, so silence or an exit 2 would
        # read as a broken flag rather than as a moved suite. It deliberately does
        # NOT print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("migrate-manifest.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_migrate_manifest.py - run that file instead.")
        return 0
    args = [a for a in argv if not a.startswith("--")]
    flags = set(a for a in argv if a.startswith("--"))
    out = None
    for a in argv:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]
    if len(args) != 1:
        sys.stderr.write("usage: migrate-manifest.py <manifest> "
                         "[--dry-run] [--force] [--renumber] [--out=<index>]\n")
        return 2
    code, msg = migrate(args[0], dry_run="--dry-run" in flags,
                        force="--force" in flags, renumber="--renumber" in flags, out=out)
    (sys.stderr if code else sys.stdout).write(msg + "\n")
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    raise SystemExit(main(sys.argv[1:]))
