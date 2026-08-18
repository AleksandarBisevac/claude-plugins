#!/usr/bin/env python3
"""
The commands around the audit trail: append a row, verify the chain, show it, archive it.

    audit-journal.py append  --action <a> [--target <path>] [--summary <text>]
    audit-journal.py verify  [--json]
    audit-journal.py show    [--limit N] [--json] [--target <path>]
    audit-journal.py archive [--before YYYY-MM]
      (every command takes --project DIR; default the current directory)

Exit codes: 0 healthy (warnings allowed) - 1 findings (the chain does not hold) -
2 usage error.

The trail itself -- the row shape, the hash chain, where a journal lives, and what
`verify` actually checks -- is `_journal_io.py` at layer 1, imported below. It used
to be this file's body, and moving it was not tidying: `_help` (layer 3) and
`audit-doctor` (layer 7) both needed it and both reached this entry point through
`_loader`, two of the seventeen edges `_deps.KNOWN_LAYER_DEBT` recorded, and
`hooks/_config.py` was loading the whole command on every tool call to resolve one
directory path.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_audit_journal.py` - see `plugins/audit/tests/_harness.py`.
"""
import argparse
import json
import os
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

import _journal_io  # noqa: E402  (the trail this command is a front end for)

# The trail, under the names this command has always called it by. NOT copies:
# `_journal_io` (layer 1) owns every one of them, and `tests/test_audit_journal.py`
# asks for them by hand across 112 cases about the trail AS THIS COMMAND SEES IT.
# `tests/test__journal_io.py` pins each name to be that module's own object, so a
# second implementation here fails a case rather than drifting.
ROW_VERSION = _journal_io.ROW_VERSION
DETAILS_VERSION = _journal_io.DETAILS_VERSION
DETAILS_KEYS = _journal_io.DETAILS_KEYS
CHANGE_KEYS = _journal_io.CHANGE_KEYS
MAX_CHANGES = _journal_io.MAX_CHANGES
MAX_VALUE_CHARS = _journal_io.MAX_VALUE_CHARS
MAX_DETAILS_BYTES = _journal_io.MAX_DETAILS_BYTES
DEFAULT_DIRNAME = _journal_io.DEFAULT_DIRNAME
ARCHIVE_DIRNAME = _journal_io.ARCHIVE_DIRNAME
DEFAULT_MANIFEST = _journal_io.DEFAULT_MANIFEST
GENESIS = _journal_io.GENESIS
LOCK_STALE_SECONDS = _journal_io.LOCK_STALE_SECONDS
LOCK_WAIT_SECONDS = _journal_io.LOCK_WAIT_SECONDS
_MONTH_RE = _journal_io._MONTH_RE
_SAFE = _journal_io._SAFE

load_config = _journal_io.load_config
enabled = _journal_io.enabled
journal_dir = _journal_io.journal_dir
in_journal = _journal_io.in_journal
canonical = _journal_io.canonical
row_hash = _journal_io.row_hash
genesis_prev = _journal_io.genesis_prev
file_hash = _journal_io.file_hash
writer_id = _journal_io.writer_id
month_of = _journal_io.month_of
file_for = _journal_io.file_for
read_file = _journal_io.read_file
journal_files = _journal_io.journal_files
read_all = _journal_io.read_all
normalise_details = _journal_io.normalise_details
append = _journal_io.append
verify = _journal_io.verify
_normalise = _journal_io._normalise
_append = _journal_io._append
_git_status_sets = _journal_io._git_status_sets
_git_anchor_finding = _journal_io._git_anchor_finding


# --- commands -----------------------------------------------------------------
def cmd_append(args, out):
    project = os.path.abspath(args.project)
    config = load_config(project)
    if not enabled(config):
        out("[audit-journal] journal disabled (journal.enabled false) -- "
            "nothing written")
        return 0
    try:
        row, _path = _append(project, {
            "action": args.action, "target": args.target or "",
            "summary": args.summary or "",
            "details": getattr(args, "_details", None),
            "actor": {"author": args.author, "sessionId": args.session,
                      "via": args.via}}, config=config)
    except Exception as exc:
        out("[audit-journal] could not append: %s" % exc)
        return 1
    out("[audit-journal] %s %s  %s" % (row["ts"], row["action"],
                                       row["hash"][:12]))
    return 0


def cmd_verify(args, out):
    project = os.path.abspath(args.project)
    res = verify(project)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        return 1 if res["findings"] else 0
    if not res["exists"]:
        out("[audit-journal] no journal yet at %s" % res["dir"])
        return 0
    for line in res["warnings"]:
        out("WARNING: " + line)
    for line in res["findings"]:
        out("FINDING: " + line)
    if res["findings"]:
        out("\nBROKEN: %d finding(s) across %d row(s) in %s"
            % (len(res["findings"]), res["rows"], res["dir"]))
        return 1
    out("OK: %d row(s) in %d file(s) chain cleanly%s"
        % (res["rows"], len(res["files"]),
           " (%d warning(s))" % len(res["warnings"]) if res["warnings"] else ""))
    return 0


def cmd_archive(args, out):
    """Move whole month-files into <journal>/archive/ -- `git mv`, never a
    rewrite, because the hash chain survives only untouched bytes and the
    genesis seed is the file's BASENAME: a moved file verifies exactly as it
    did live, and git carries its committed history across the move so the
    git anchor keeps holding.

    Default: every month-file older than the current month. --before YYYY-MM
    archives strictly older months. The current month (and anything newer) is
    never archived -- it is still being written.

    DECISION (pinned, v0.37 D): an UNTRACKED file is moved with os.rename
    rather than refused. `git mv` fails on untracked files, and the reason
    git mv is the mechanism -- carrying COMMITTED history across the move --
    does not exist for a file with no committed past: a plain rename loses
    nothing the chain or the anchor ever had. The doctor's never-committed
    warning follows the file into archive/ and keeps nagging until it is
    committed, which is the honest state of affairs.
    """
    import shutil
    import subprocess

    def git(directory, *a):
        try:
            res = subprocess.run(["git", "-C", directory] + list(a),
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=30)
            return res.returncode, (res.stdout or b"").decode("utf-8",
                                                              "replace"), \
                (res.stderr or b"").decode("utf-8", "replace")
        except Exception as exc:
            return 1, "", str(exc)

    project = os.path.abspath(args.project)
    config = load_config(project)
    directory = journal_dir(project, config)
    current = time.strftime("%Y-%m", time.gmtime())
    before = (args.before or "").strip()
    if before and not _MONTH_RE.match(before):
        out("[audit-journal] --before must be YYYY-MM (got %r)" % before)
        return 2
    cutoff = before or current
    if cutoff > current:
        out("[audit-journal] --before %s reaches into the future; the current "
            "month and anything newer is still being written and is never "
            "archived -- archiving everything older than %s instead"
            % (before, current))
        cutoff = current
    if not os.path.isdir(directory):
        out("[audit-journal] nothing to archive: no journal at %s" % directory)
        return 0
    in_repo = False
    if shutil.which("git"):
        rc, txt, _err = git(directory, "rev-parse", "--is-inside-work-tree")
        in_repo = rc == 0 and txt.strip() == "true"
    if not in_repo:
        # The whole point of archiving by `git mv` is that committed history
        # follows the move and the git anchor keeps holding. No repository
        # means no history to carry -- and an archive that silently plain-moved
        # files here would teach people the operation is safe anywhere.
        out("[audit-journal] not inside a git repository (or git is not on "
            "PATH): archive moves files with `git mv` so their committed "
            "history follows the move and the git anchor keeps holding -- "
            "with no repository there is nothing to carry. Run `git init` "
            "and commit the journal first.")
        return 2
    moved, kept, failed = [], [], []
    arch = os.path.join(directory, ARCHIVE_DIRNAME)
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        month = name[:7]
        if not _MONTH_RE.match(month):
            kept.append("%s: kept -- no YYYY-MM month prefix to judge it by"
                        % name)
            continue
        if month >= cutoff:
            continue        # current/future months and >= --before stay live
        if os.path.exists(os.path.join(arch, name)):
            kept.append("%s: kept -- archive/%s already exists; refusing to "
                        "overwrite it (verify will warn about the duplicate)"
                        % (name, name))
            continue
        os.makedirs(arch, exist_ok=True)
        rc, _txt, _err = git(directory, "ls-files", "--error-unmatch",
                             "--", name)
        if rc == 0:
            rc2, _txt2, err2 = git(directory, "mv", name,
                                   "%s/%s" % (ARCHIVE_DIRNAME, name))
            if rc2 != 0:
                failed.append("%s: git mv failed (%s)"
                              % (name, err2.strip() or "unknown error"))
                continue
            moved.append("%s -> archive/%s (git mv; committed history "
                         "follows the move)" % (name, name))
        else:
            try:
                os.rename(os.path.join(directory, name),
                          os.path.join(arch, name))
            except OSError as exc:
                failed.append("%s: could not move (%s)" % (name, exc))
                continue
            moved.append("%s -> archive/%s (renamed; never committed, so "
                         "there was no git history to carry)" % (name, name))
    for line in kept:
        out("[audit-journal] " + line)
    for line in failed:
        out("[audit-journal] FAILED " + line)
    for line in moved:
        out("[audit-journal] archived " + line)
    if moved:
        out("[audit-journal] %d file(s) moved, 0 bytes rewritten: a hash "
            "chain survives only untouched bytes, and its seed is the file's "
            "basename, so every moved file verifies exactly as it did. "
            "Commit the archive/ directory so the git anchor pins it."
            % len(moved))
    elif not kept and not failed:
        out("[audit-journal] nothing to archive: no month-file older than %s "
            "in %s" % (cutoff, directory))
    return 1 if failed else 0


def cmd_show(args, out):
    project = os.path.abspath(args.project)
    rows = read_all(project)
    if args.target:
        rows = [r for r in rows if r.get("target") == args.target]
    if args.limit > 0:
        rows = rows[-args.limit:]
    if args.as_json:
        out(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        out("[audit-journal] no rows")
        return 0
    for r in rows:
        actor = r.get("actor") or {}
        out("%s  %-18s %-28s %s"
            % (r.get("ts"), r.get("action"), (r.get("target") or "")[-28:],
               actor.get("author") or actor.get("sessionId") or "unknown"))
        if r.get("summary"):
            out("    %s" % r["summary"])
    return 0


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-journal.py", add_help=True)
    p.add_argument("command", choices=["append", "verify", "show", "archive"])
    p.add_argument("--project", default=".")
    p.add_argument("--before", default="")
    p.add_argument("--action", default="")
    p.add_argument("--target", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--details", default=None)
    p.add_argument("--via", default="cli")
    p.add_argument("--author", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not os.path.isdir(args.project):
        out("[audit-journal] not a directory: %s" % args.project)
        return 2
    if args.command == "append" and not args.action.strip():
        out("[audit-journal] append needs --action")
        return 2
    # --details is parsed HERE, before anything is written: malformed JSON is a
    # usage error (2), never a silently plain row -- a caller passing structured
    # news must find out it was dropped.
    args._details = None
    if args.command == "append" and args.details:
        try:
            parsed = json.loads(args.details)
        except Exception as exc:
            out("[audit-journal] --details is not valid JSON: %s" % exc)
            return 2
        if not isinstance(parsed, dict):
            out("[audit-journal] --details must be a JSON object")
            return 2
        args._details = parsed
    try:
        if args.command == "append":
            return cmd_append(args, out)
        if args.command == "verify":
            return cmd_verify(args, out)
        if args.command == "archive":
            return cmd_archive(args, out)
        return cmd_show(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-journal] internal error: %s" % exc)
        return 2


if __name__ == "__main__":
    from _output import safe_stdio       # same dir; sys.path[0] when run directly
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to `main`, which would read the flag
        # as an unknown command. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-journal.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_journal.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
