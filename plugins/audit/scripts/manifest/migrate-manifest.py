#!/usr/bin/env python3
"""
Switch an audit manifest between its two layouts - one file, or an index plus one shard
per phase - dependency-free (stdlib only).

The sharded layout keeps the shared, rarely-churned data (meta, bugs, fileIndex) in the
index and each phase's body in `phases/<phaseId>.json`, so a phase command loads only its
own phase (fewer tokens) and two parallel phase branches edit different files (no manifest
merge conflict). The single-file layout is one document, one diff, no index. Reading is
transparent either way - every script + hook already loads both via _manifest_io - so
neither shape is ever out of date and changing layout stays opt-in.

BOTH DIRECTIONS, UNDER ONE DISCIPLINE. `--to=sharded` is the default, so every existing
invocation still means what it always meant; `--to=single-file` inlines the shards back
into one document. Each direction runs the same steps in the same order: validate the
SOURCE, refuse a mid-run change unless forced, back the original up, write atomically,
re-read the result and check it both validates and reads as the layout that was asked
for - and RESTORE the backup on any failure.

A backup is still a restore point and not an undo: copying `<manifest>.bak-<UTC>` back by
hand discards every manifest write made after the layout change. Say that wherever the
backup is mentioned. What the reverse direction changes is that going back is no longer
something a user has to do by hand at all.

NO LOCK IS TAKEN HERE, deliberately. The index lock belongs to the command driving this -
`commands/migrate.md` runs `audit-lock.py acquire index` around the call - so acquiring it
in this file would be a second, uncoordinated acquisition by the process already holding
it.

Usage:
  migrate-manifest.py <manifest> [--to=sharded|single-file]
                                 [--dry-run] [--force] [--renumber] [--out=<path>]
  migrate-manifest.py --selftest

Safe by default:
  - ALREADY in the requested layout -> nothing to do (exit 0)
  - validates the SOURCE first; refuses to convert a manifest with findings (exit 1)
    (--renumber first repairs duplicate BUG- ids - the common cross-machine collision -
     and is meaningful in BOTH directions: the source is assembled and validated either
     way, and the repair is written out with the rest of the manifest)
  - refuses if any phase is `in_progress` (a mid-run layout change corrupts the run);
    override with --force
  - refuses, in the sharded direction, when two phase ids sanitise to one shard
    FILENAME: the second body would silently replace the first. `--dry-run` refuses
    it too, so the preview is not the step that discovers it
  - refuses, in the sharded direction, when no phase carries an id: a split with
    nothing to shard reads as single-file whatever the version says
  - backs up the original to <manifest>.bak-<UTC> before writing
  - re-reads the RESULT: it must validate AND read as the requested layout by BOTH
    readings of the layout - the phase stubs and `meta.version`. On any failure it
    RESTORES the backup and exits non-zero
  - `--to=single-file` then moves the emptied shard directory aside under a
    `.bak-<UTC>` name. A rename, so it cannot half-apply, and it deletes nothing

Exit codes: 0 ok / already in that layout - 1 refused or validation failure -
2 usage/unreadable.

This script carries no `--selftest` of its own any more; its cases live in
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


# A budget of its own, because `_output.EVIDENCE_BUDGET` is sized for a line a
# doctor or a validator prints INSIDE a sentence, and this one is a refusal printed
# as an indented block with one finding per line. The reader is being told to go and
# fix them, so the list is the whole point of the message rather than an aside in it.
_MIGRATE_FINDING_BUDGET = 1200


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


def layout_names():
    """The layout names `--to` accepts, in one fixed order.

    Read off `_manifest_io.LAYOUT_VERSION` rather than restated here: the names and the
    `meta.version` value each one stands for are one fact, and a second copy of the list
    is how a layout gets added to the writer and not to the flag that selects it.
    """
    return sorted(_mio.LAYOUT_VERSION)


def shardable_phases(manifest):
    """The phases a split would actually move into a shard: every phase dict with an id.

    `split_manifest` passes anything else through into the index untouched, so a
    manifest with none of these splits into an index carrying no `shard` pointer at all
    — a file stamped with the sharded version that `is_sharded()`, and therefore every
    consumer in the plugin, reads as single-file. That is the one state the two readings
    of the layout must never be left in, so the sharded direction refuses it by name
    instead of writing it.
    """
    return [p for p in (manifest.get("phases") or [])
            if isinstance(p, dict) and p.get("id")]


def check_written_layout(target, want):
    """Raise unless the manifest just written at `target` reads as `want` BOTH ways.

    THE LAYOUT HAS TWO INDEPENDENT READINGS and this is where they are held together:
    `_mio.layout_of()` reads the phase stubs, `_mio.declared_layout()` reads
    `meta.version`, and they agreed on the forward migration only because
    `split_manifest` happens to write the sharded number. A write that satisfies one and
    not the other produces a manifest whose layout depends on who is asking — and the
    check runs here, before the backup is let go, so the answer to a disagreement is a
    restore rather than a corrupted plan.

    A `meta.version` naming no layout at all is a failure and not a pass: silence is
    what a caller reading only `is_sharded()` would never notice.
    """
    raw = _mio.read_json(target)
    structural = _mio.layout_of(raw)
    if structural != want:
        raise RuntimeError("wrote the %s layout but the phase stubs read as %s"
                           % (want, structural))
    declared = _mio.declared_layout(raw)
    if declared != want:
        raise RuntimeError("wrote the %s layout but meta.version names %s"
                           % (want, declared or "no layout at all"))


def _revalidate(target, want, vm):
    """Re-read what was just written and refuse it unless it is a valid manifest IN THE
    LAYOUT THAT WAS ASKED FOR. Raises; the caller restores the backup.

    Two questions, and the second is why the layout check cannot be left to the
    validator: `validate()` is a pure function of the ASSEMBLED dict and is layout-blind
    by design, so it passes a document written in the wrong shape entirely.
    """
    check_written_layout(target, want)
    result = _mio.load_manifest(target)
    findings, _ = vm.validate(result)
    if findings:
        raise RuntimeError("post-write validation failed: %s" % "; ".join(findings[:4]))


def _retire_shard_dir(raw_index, index_path, stamp):
    """Move the now-dead shard directory aside. Returns a line saying what happened.

    MOVED, NOT DELETED, AND IN ONE `os.rename`. The three options were all real costs.
    Leaving live-looking shard files behind invites an edit to a file nothing reads any
    more. Deleting a user's plan data cannot be undone. And a delete that fails halfway
    leaves a shard set with holes, which is worse than either. A rename is a single
    atomic operation within one filesystem: it cannot half-apply, it removes nothing,
    and it leaves the working tree with no file that looks live and is not. What it
    costs is a directory the user has to clean up, named the way the backup file beside
    it is named so the two read as one pair.

    The directory comes from `_mio.shard_dir_to_retire()`, which reads the index's own
    pointers instead of assuming the default — and when there is no single directory of
    its own to retire, its reason is reported rather than swallowed: shards left in
    place with nothing said about them is the outcome this whole function exists to
    avoid.
    """
    sdir, why = _mio.shard_dir_to_retire(raw_index, index_path)
    if not sdir:
        return "shards left in place (%s)" % why
    parked = "%s.bak-%s" % (sdir, stamp)
    if os.path.exists(parked):
        raise RuntimeError("cannot move %s aside: %s already exists" % (sdir, parked))
    os.rename(sdir, parked)
    return "shards moved aside: %s" % parked


def _restore(path, backup, target):
    """Put the original manifest back, and say what was done. Returns the phrase for
    the failure message.

    Two shapes, because "restored" over a `--out` run would be a claim about a file the
    run never wrote to. When there is no backup the source is intact by construction and
    what needs saying instead is that `target` may be a PARTIAL write: it is a new file
    nothing has validated, and reporting only the exception would leave the reader to
    discover that themselves.
    """
    if backup and os.path.exists(backup):
        shutil.copy2(backup, path)
        return "restored %s" % backup
    return ("%s was not written to, but %s may be an incomplete write"
            % (path, target))


def _preview(raw_index, index_path, manifest, to, target):
    """The `--dry-run` line for either direction. Names the files that would appear and,
    for the reverse, the directory that would be moved aside — a preview that showed
    only the write would leave the one irreversible-looking step unmentioned."""
    if to == "sharded":
        shards = _mio.split_manifest(manifest)[1]
        # `_mio.shard_rel_path`, not a fourth spelling of the same filename: this
        # line hardcoded the default directory AND rebuilt the name by hand, so a
        # preview could name files the writer would not write.
        return ("DRY RUN: would write index %s + %d shard(s): %s"
                % (target, len(shards),
                   ", ".join(_mio.shard_rel_path(p) for p in shards)))
    sdir, why = _mio.shard_dir_to_retire(raw_index, index_path)
    return ("DRY RUN: would write one file %s (%d phase(s) inlined) and %s"
            % (target, len(manifest.get("phases") or []),
               ("move %s aside under a .bak-<UTC> name" % sdir) if sdir
               else ("leave the shards in place: %s" % why)))


def migrate(path, *, to="sharded", dry_run=False, force=False, renumber=False, out=None):
    """Change the manifest's LAYOUT. Returns (exit_code, message).

    `to` names a layout rather than a direction, and defaults to "sharded" so every
    invocation written before the reverse existed keeps its meaning. Both directions run
    the same steps in the same order — see the module docstring — and the module keeps
    the name it had because that is what the command, the docs and the transcripts call.
    """
    if to not in _mio.LAYOUT_VERSION:
        return 2, "unknown layout %r (expected %s)" % (to, " or ".join(layout_names()))
    # detect the CURRENT layout from the RAW index, before assembly
    try:
        raw = _mio._read_json(path)
    except Exception as exc:
        return 2, "cannot read/parse %s: %s" % (path, exc)
    current = _mio.layout_of(raw)
    if current == to:
        return 0, "already %s: %s (nothing to do)" % (to, path)
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
        return 1, ("source manifest has %d finding(s); fix them before changing layout"
                   "%s:\n  - %s" % (len(findings),
                   " (or pass --renumber for duplicate BUG- ids)"
                   if any("duplicate" in f.lower() and "BUG-" in f for f in findings) else "",
                   _output.some_of(findings, budget=_MIGRATE_FINDING_BUDGET,
                                   sep="\n  - ")))

    blocked = _in_progress_phases(manifest)
    if blocked and not force:
        return 1, ("refusing: phase(s) %s are in_progress — changing layout mid-run "
                   "corrupts the run. Finish/pause them, or pass --force."
                   % ", ".join(str(b) for b in blocked))
    if to == "sharded" and not shardable_phases(manifest):
        return 1, ("refusing: no phase in %s carries an id, so a split has nothing to "
                   "put in a shard — the result would be stamped as sharded and still "
                   "read as single-file everywhere. Add a phase first." % path)
    # `_mio.save_sharded` refuses this too, and that refusal is the one that
    # protects every OTHER writer. It is asked again here because a `--dry-run`
    # never reaches the writer: a preview that listed the shard files and said
    # nothing about two of them being one file would send the user into the real
    # run to find out. It returns the same code the neighbouring refusals do, and
    # the ids come from `_mio` so the two messages cannot name different pairs.
    collisions = _mio.shard_name_collisions(manifest) if to == "sharded" else []
    if collisions:
        return 1, ("refusing: %s — two ids the shard filename cannot tell apart "
                   "would be written to one file and the second would silently "
                   "replace the first. Rename one of them, then migrate."
                   % _mio.describe_shard_collisions(collisions))

    target = out or path
    if dry_run:
        return 0, _preview(raw, path, manifest, to, target)

    stamp = _utc_stamp()
    backup = None
    if out is None:                     # in-place: back up the original first
        backup = "%s.bak-%s" % (path, stamp)
        shutil.copy2(path, backup)
    retired = ""
    try:
        if to == "sharded":
            written = _mio.save_sharded(target, manifest)
        else:
            written = _mio.save_single_file(target, manifest)
        _revalidate(target, to, vm)
        # LAST, and only in place: every step above is undone by putting the index
        # back, and this one is the only one that touches a file the restore does not
        # cover. Moving the shards before the result had validated would mean a
        # restored index pointing at a directory that had been renamed out from under
        # it. Under `--out` the source is untouched and its shards stay live.
        if to == "single-file" and out is None:
            retired = _retire_shard_dir(raw, path, stamp)
    except Exception as exc:
        return 1, "layout change failed (%s): %s" % (_restore(path, backup, target), exc)

    msg = "%s -> %s: %s" % (current, to, target)
    if backup:
        msg += "\n  backup (the manifest file only): %s" % backup
    if retired:
        msg += "\n  " + retired
    if to == "single-file" and out is not None:
        msg += "\n  source left sharded, its shards still live: %s" % path
    msg += "\n  " + "\n  ".join(written)
    return 0, msg


# --- cli ------------------------------------------------------------------------
_BARE_FLAGS = ("--dry-run", "--force", "--renumber")
_VALUE_FLAGS = ("--to", "--out")
# ONE SPELLING FOR A VALUE, and it is the `=` form. `--out=` was already the only
# spelling this script took, the command docs invoke `--to=` the same way, and a parser
# that accepts both has to consume the NEXT argv entry - which is how `--to <manifest>`
# swallows the path and leaves the run arguing about a missing positional instead of
# about the flag. The space form is refused BY NAME rather than absorbed.
_ACCEPTED = ", ".join(_BARE_FLAGS + tuple("%s=<value>" % f for f in _VALUE_FLAGS))
_USAGE = ("usage: migrate-manifest.py <manifest> [--to=sharded|single-file] "
          "[--dry-run] [--force] [--renumber] [--out=<path>]")


def parse_args(argv):
    """`(opts, error)` — the parsed command line, or None and a message to print.

    A function rather than a few lines inside `main()` because the flag surface is now
    the part most easily got wrong, and this way it has cases that need no manifest on
    disk.

    IT FAILS CLOSED. This used to build a `set` of everything starting with `--` and
    look only for the three it knew, so anything else was silently dropped and the run
    PROCEEDED: `--dryrun`, a plausible typo for `--dry-run`, migrated the manifest for
    real and reported success. With a `--to` in the surface that is no longer merely a
    lost flag — `--to=singlefile` or `--single-file` quietly ignored leaves the default
    in place and converts the user's plan the opposite way from the one they asked for.
    So an argument this function does not understand can never mean "proceed": every
    flag, and the layout `--to` names, is checked against a known set, and anything else
    is refused with the offending spelling and the accepted ones both named.
    """
    values, bare, rest = {}, [], []
    for arg in argv:
        if not arg.startswith("--"):
            rest.append(arg)
            continue
        name, eq, inline = arg.partition("=")
        if name in _BARE_FLAGS:
            if eq:
                return None, ("%s takes no value; accepted: %s" % (name, _ACCEPTED))
            bare.append(name)
        elif name in _VALUE_FLAGS:
            if not eq:
                return None, ("%s takes its value with an = sign (%s=...), not a "
                              "space; accepted: %s" % (name, name, _ACCEPTED))
            values[name] = inline
        else:
            return None, ("unknown flag %s; accepted: %s" % (name, _ACCEPTED))
    if len(rest) != 1:
        return None, ("expected exactly one manifest path, got %d" % len(rest))
    to = values.get("--to", "sharded")
    if to not in _mio.LAYOUT_VERSION:
        return None, ("unknown layout %r; accepted: %s"
                      % (to, ", ".join(layout_names())))
    return {"path": rest[0], "to": to, "dry_run": "--dry-run" in bare,
            "force": "--force" in bare, "renumber": "--renumber" in bare,
            "out": values.get("--out")}, ""


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
    opts, err = parse_args(argv)
    if opts is None:
        sys.stderr.write("%s\n%s\n" % (err, _USAGE))
        return 2
    code, msg = migrate(opts["path"], to=opts["to"], dry_run=opts["dry_run"],
                        force=opts["force"], renumber=opts["renumber"], out=opts["out"])
    (sys.stderr if code else sys.stdout).write(msg + "\n")
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    raise SystemExit(main(sys.argv[1:]))
