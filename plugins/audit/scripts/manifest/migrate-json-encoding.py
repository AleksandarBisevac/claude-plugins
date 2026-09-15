#!/usr/bin/env python3
"""
migrate-json-encoding.py -- rewrite the files of ONE manifest in the escaping this
plugin now writes, in a single pass, so no document is left in the other family.

WHY A MIGRATION AND NOT A NOTE. The plugin used to take the escaping as an
argument, so two writers produced two byte shapes for the same document, and the
files already on disk are in whichever shape last wrote them. Leaving them there
does not settle: the next ordinary command rewrites one file, the diff shows every
line carrying a non-ASCII character as changed, and a shard merge that should have
been the lines that moved becomes a whole-file conflict on exactly the parallel
phases the sharded layout exists to make possible. `_manifest_io.json_document` is
the choosing site and says which direction and why; this command is how the tree
catches up with it, once.

WHAT IT OWNS, AND WHAT IT WILL NOT TOUCH. The files of the manifest it is pointed
at: the index, and every shard that index NAMES. Nothing else -- not the project's
config, not a sibling manifest, not a file a `shard` value points at from outside
the index's own directory, which is refused by name rather than followed. A
migration that widened its own scope would be rewriting a project's files on the
strength of a path it was handed.

ALL OR NOTHING, AND THE ORDER IS THE POINT:

  1. take the index lock, so a running command cannot write between the read and
     the write;
  2. read EVERY owned file and compute its new text before touching any of them --
     a file that cannot be read or parsed refuses the whole pass, because a
     half-migrated manifest is worse than an un-migrated one;
  3. validate the assembled manifest BEFORE the save, and refuse if it has
     findings: this command rewrites bytes, and rewriting the bytes of a document
     that was already broken makes the break harder to read;
  4. write only the files whose bytes actually change, each atomically;
  5. re-read from disk and validate again -- rolling every file back byte for byte
     if the result does not stand.

It says what it changed AND what it could not, always. A file already in the
encoding is reported as such rather than silently omitted: "nothing to do" and
"nothing was looked at" are different answers and a caller has to be able to tell
them apart.

Usage:
  migrate-json-encoding.py <manifestPath> [--dry-run] [--project-dir DIR]
                                          [--takeover] [--json]
  migrate-json-encoding.py --selftest

Exit codes:
  0  every owned file is in the encoding (rewritten, or already there)
  1  refused, and nothing written: a file could not be read or parsed, the
     manifest had findings before the save, the write failed, or the result did
     not validate (rolled back)
  2  usage: no manifest, not a file, bad args
  3  the index lock is held by a LIVE run (audit-lock's standard message)
  4  the index lock looks abandoned -- rerun with --takeover once a human has
     confirmed (audit-lock's standard message)

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_migrate_json_encoding.py`.

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

import _manifest_io as _mio   # noqa: E402  (the loader, and the ONE document spelling)
import _manifest_rules as _rules  # noqa: E402  (the referential rules, for the two checks)
import _panel_write           # noqa: E402  (the index lock, the project walk and the
#                                            snapshot/rollback pair -- reached by
#                                            identity, so this command and the other
#                                            manifest writers cannot drift)

E_INVALID, E_USAGE, E_LIVE, E_STALE = 1, 2, 3, 4

REWRITE = "rewrite"        # the file is in the other family and will be rewritten
ALREADY = "already"        # the file is already in the encoding
UNREADABLE = "unreadable"  # it could not be read or parsed; the pass refuses


# --- what one manifest owns -------------------------------------------------------
def owned_files(mpath):
    """{"paths": [...], "refused": [(path, why)]} -- the files of the manifest at
    `mpath`, and the ones it names that this command will not follow.

    The index is always owned. In the sharded layout each `phases[].shard` is
    owned too, resolved against the index's own directory -- and a value that
    escapes that directory (absolute, or climbing out with `..`) is REFUSED and
    named rather than followed. The manifest is a document a project may have
    hand-edited, so its contents decide which files get rewritten; bounding that
    to the index's own directory is what keeps a handed-in path from turning this
    into a writer of somebody else's files.

    A shard the index names and the filesystem does not have is refused the same
    way: this command rewrites files, and inventing one is not rewriting it.
    """
    base = os.path.dirname(os.path.abspath(mpath))
    paths = [os.path.abspath(mpath)]
    refused = []
    try:
        index = _mio.read_json(mpath)
    except Exception as exc:
        return {"paths": paths, "refused": [(os.path.abspath(mpath),
                                             "cannot be read: %s" % (exc,))]}
    if not isinstance(index, dict):
        return {"paths": paths, "refused": refused}
    for stub in (index.get("phases") or []):
        if not isinstance(stub, dict):
            continue
        rel = stub.get("shard")
        if not rel or not isinstance(rel, str):
            continue
        if os.path.isabs(rel):
            refused.append((rel, "an absolute `shard` path - a manifest may only "
                                 "name files inside its own directory"))
            continue
        full = os.path.abspath(os.path.join(base, rel))
        if os.path.relpath(full, base).split(os.sep)[0] == "..":
            refused.append((rel, "a `shard` path that climbs out of %s - a "
                                 "manifest may only name files inside its own "
                                 "directory" % (base,)))
            continue
        if not os.path.isfile(full):
            refused.append((rel, "named by the index and not on disk - nothing "
                                 "to rewrite"))
            continue
        if full not in paths:
            paths.append(full)
    return {"paths": paths, "refused": refused}


# --- what each file would become ---------------------------------------------------
def plan_file(path):
    """{"path", "verdict", "obj", "why"} for one owned file.

    The comparison is against `_manifest_io.json_document`, and the escaping is
    never re-derived here: a migration that spelled it itself would be the second
    spelling it exists to remove. `obj` is what the writer is handed, so the
    bytes that land come from the same function the comparison used.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            current = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return {"path": path, "verdict": UNREADABLE, "obj": None,
                "why": "cannot be read: %s" % (exc,)}
    try:
        obj = json.loads(current)
    except ValueError as exc:
        return {"path": path, "verdict": UNREADABLE, "obj": None,
                "why": "is not JSON: %s" % (exc,)}
    if _mio.json_document(obj, 2) == current:
        return {"path": path, "verdict": ALREADY, "obj": obj, "why": ""}
    return {"path": path, "verdict": REWRITE, "obj": obj, "why": ""}


def plan(paths):
    """[plan_file(p) for p in paths] -- every owned file judged before any of them
    is written. Computing the whole plan first is what makes the refusal total:
    the unreadable file is found before the first byte lands, not after half the
    manifest has been rewritten."""
    return [plan_file(p) for p in paths]


def summarise(rows, refused):
    """{"rewrite", "already", "unreadable", "refused"} -- the plan as the four
    lists a report and a `--json` payload both render. One shape, so the human
    line and the machine payload cannot disagree about what happened."""
    return {"rewrite": [r["path"] for r in rows if r["verdict"] == REWRITE],
            "already": [r["path"] for r in rows if r["verdict"] == ALREADY],
            "unreadable": [(r["path"], r["why"]) for r in rows
                           if r["verdict"] == UNREADABLE],
            "refused": list(refused)}


# --- the run ----------------------------------------------------------------------
def _validate(mpath):
    """(findings, warnings) for the manifest as it stands on disk, or a finding
    saying it could not be assembled. Never raises: a validator that raises turns
    a refusal into a traceback."""
    try:
        return _rules.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        return (["the manifest could not be assembled: %s" % (exc,)], [])


def _rel(path, project):
    return _output.posix_rel(path, project)


def _report(out, view, project, dry_run):
    """Every class, always -- including the empty ones. A report that printed only
    what it changed would spell "there was nothing to do" and "it never looked"
    the same way."""
    for path, why in view["refused"]:
        out("  not mine: %s -- %s" % (path, why))
    for path, why in view["unreadable"]:
        out("  unreadable: %s -- %s" % (_rel(path, project), why))
    for path in view["already"]:
        out("  already in the encoding: %s" % (_rel(path, project),))
    for path in view["rewrite"]:
        out("  %s: %s" % ("would rewrite" if dry_run else "rewrote",
                          _rel(path, project)))


def _locked_migrate(args, project, mpath, out):
    owned = owned_files(mpath)
    rows = plan(owned["paths"])
    view = summarise(rows, owned["refused"])

    if view["unreadable"]:
        out("[migrate-json-encoding] REFUSED: nothing written. A file this "
            "manifest owns could not be read, and a half-migrated manifest is "
            "worse than an un-migrated one:")
        _report(out, view, project, True)
        if args.as_json:
            out(json.dumps({"ok": False, "why": "unreadable",
                            "applied": False, "view": view},
                           indent=2, sort_keys=True, default=str))
        return E_INVALID

    # BEFORE the save, not only after it. This command rewrites bytes and changes
    # no value, so a manifest that was already invalid stays exactly as invalid --
    # and re-spelling a broken document makes the break harder to read in the diff
    # that has to repair it.
    findings, warnings = _validate(mpath)
    if findings:
        out("[migrate-json-encoding] REFUSED: the manifest has findings, and "
            "nothing was written. Fix these, then run this again:")
        for line in findings:
            out("FINDING: " + line)
        # The classes are printed on THIS path too. A refusal that said only what
        # stopped it would leave the operator unable to tell a manifest this
        # command had read from one it had never opened.
        _report(out, view, project, True)
        if args.as_json:
            out(json.dumps({"ok": False, "why": "invalid", "applied": False,
                            "findings": findings, "view": view},
                           indent=2, sort_keys=True, default=str))
        return E_INVALID

    if args.dry_run or not view["rewrite"]:
        out("[migrate-json-encoding] %s"
            % ("dry run -- nothing written" if args.dry_run
               else "every owned file is already in the encoding"))
        _report(out, view, project, True)
        if args.as_json:
            out(json.dumps({"ok": True, "applied": False,
                            "dryRun": bool(args.dry_run),
                            "warnings": warnings, "view": view},
                           indent=2, sort_keys=True, default=str))
        return 0

    snap = _panel_write.snapshot(owned["paths"])
    try:
        for row in rows:
            if row["verdict"] == REWRITE:
                _mio.atomic_write_json(row["path"], row["obj"], indent=2)
    except Exception as exc:
        _panel_write.restore(snap)
        out("[migrate-json-encoding] write failed -- every file restored: %s"
            % (exc,))
        return E_INVALID

    # Re-read from DISK rather than trusting the objects just written: the claim
    # is about what LANDED, and a check against the in-memory copy would be
    # grading the intention.
    after, warnings = _validate(mpath)
    if after:
        _panel_write.restore(snap)
        out("[migrate-json-encoding] REFUSED: the rewritten manifest does not "
            "validate -- every file was rolled back, nothing kept:")
        for line in after:
            out("FINDING: " + line)
        return E_INVALID

    out("[migrate-json-encoding] done")
    _report(out, view, project, False)
    if args.as_json:
        out(json.dumps({"ok": True, "applied": True, "dryRun": False,
                        "warnings": warnings, "view": view},
                       indent=2, sort_keys=True, default=str))
    return 0


def cmd_migrate(args, out):
    if not args.manifest:
        out("[migrate-json-encoding] needs a manifest path")
        return E_USAGE
    mpath = os.path.abspath(args.manifest)
    if not os.path.isfile(mpath):
        out("[migrate-json-encoding] manifest not found: %s" % (mpath,))
        return E_USAGE
    if args.project_dir:
        project = os.path.abspath(args.project_dir)
    else:
        project = _panel_write.project_of_manifest(mpath)
    if not os.path.isdir(project):
        out("[migrate-json-encoding] not a directory: %s" % (project,))
        return E_USAGE
    config = _panel_write.read_config(project)
    # The lock comes BEFORE the read, and covers the whole read-plan-write: a
    # command that wrote a shard between the plan and the save would have its
    # write reverted by this one without either side noticing.
    lock = _panel_write.acquire_index_lock(project, config, mpath,
                                           args.takeover, out,
                                           "[migrate-json-encoding]",
                                           "migrate json encoding")
    if isinstance(lock, int):
        return lock
    try:
        return _locked_migrate(args, project, mpath, out)
    finally:
        _panel_write.release_index_lock(lock)


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="migrate-json-encoding.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        return cmd_migrate(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[migrate-json-encoding] internal error: %s" % (exc,))
        return E_INVALID


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would read the flag
        # as a missing positional. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("migrate-json-encoding.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_migrate_json_encoding.py - run that "
              "file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
