#!/usr/bin/env python3
"""
The /audit concurrency lock, as code instead of prose -- dependency-free (stdlib).

Until now the lock was taken, judged and released entirely by the orchestrator's
written procedure via Bash. Nothing in the codebase acquired it; every code
reference (`audit-doctor.py`, `audit-usage.py`, `panel-server.py`) only read it.
A convention nobody can execute is not a lock, so this puts the decision in a
script that returns an exit code.

Usage:
  audit-lock.py acquire <name> [--project DIR] [--note TEXT] [--takeover]
  audit-lock.py release <name> [--project DIR] [--force]
  audit-lock.py status         [--project DIR] [--json]

This module carries no inline `--selftest` any more; its 68 cases live in
`plugins/audit/tests/test_audit_lock.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The flag is still accepted and still exits
0, pointing there.

  <name> is `index` or `phase-<phaseId>` -- the two tiers the orchestrator uses.
  --session / --pid override the identity written into the lock; they default to
  $CLAUDE_CODE_SESSION_ID and $CLAUDE_PID.

Exit codes:
  0  acquired / released / status printed
  3  held by a LIVE run -- refuse and stop
  4  held by a run that is NOT alive -- rerun with --takeover to seize it
  2  usage error
  1  internal error

WHY LIVENESS, NOT AGE
The old rule was "a lock older than 60 minutes is a crashed run". That is a proxy
for "is the holder still alive", and it is wrong in both directions:

  * FALSE STALE.  A healthy 90-minute phase run looks crashed, so the next
    session is offered a takeover, accepts it, and both then mutate the same
    shard -- and the original never learns it lost the lock. The protocol makes
    this likelier than it sounds: it says human-confirmation pauses KEEP the
    lock, and a phase run has several (high-risk task confirmation, budget
    overrun, review sign-off). A run that asks the human something and gets an
    answer after lunch is stale by the protocol's own definition while perfectly
    healthy.
  * FALSE FRESH.  A run that crashed after ten minutes holds its lock for the
    remaining fifty, and the next session is told to wait for nothing.

On the same host the real question is answerable directly: is that pid alive?
This lock only ever claimed same-machine jurisdiction anyway -- it lives in the
shared git dir, so it coordinates worktrees and clones of ONE machine, and
`phase.claim` plus the shard merge conflict are what cover other machines. So:

  same host + recorded pid alive  -> LIVE, refuse at any age
  same host + recorded pid dead   -> STALE at once, no waiting
  no pid, or another host         -> fall back to the age rule (unchanged)

BIAS: every uncertainty resolves to LIVE. A false "dead" means two writers and a
silently corrupted shard; a false "alive" means a refusal the human clears by
deleting one file, which `/audit:doctor` already tells them how to do. Those two
mistakes are not the same size, so the tie does not go to convenience.

A pid can be reused by an unrelated process, which reads as LIVE -- the same safe
direction, and the reason the recorded pid must be one that outlives the acquire
call (the orchestrator's own, via $CLAUDE_PID). This script's pid dies the
instant it exits, so it is never what gets written; with no durable pid available
we record none and stay on the age rule rather than inventing liveness.

Acquire is also race-free now: O_CREAT|O_EXCL replaces the prose's
"if the file exists ... else write it", which had a window between the two.
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

import _locks  # noqa: E402  (where a lock lives, what it may be called, is it live)

# The read side, spelled here because this file's own commands ask the same four
# questions its callers do. NOT copies: `_locks` is layer 1 and owns every one of
# them, and `tests/test_audit_lock.py` pins each name to be that module's own
# object. They moved because THREE other modules needed them and reached this
# entry point through `_loader` to get them — three of the seventeen edges
# `_deps.KNOWN_LAYER_DEBT` recorded.
STALE_MINUTES = _locks.STALE_MINUTES
pid_alive = _locks.pid_alive
_age_minutes = _locks._age_minutes
judge = _locks.judge
lock_dir = _locks.lock_dir
valid_name = _locks.valid_name
read_lock = _locks.read_lock
collect = _locks.collect
acquire = _locks.acquire
release = _locks.release
_identity = _locks._identity
_write_lock = _locks._write_lock

E_LIVE, E_STALE, E_USAGE, E_ERR = (_locks.E_LIVE, _locks.E_STALE,
                                   _locks.E_USAGE, _locks.E_ERR)


# --- commands -----------------------------------------------------------------
# Three adapters and an argument parser: that is all this file is now. Each turns
# an argparse Namespace into a call on `_locks`, which is where every one of these
# bodies used to live inline. They moved because `audit-task.py` needs to TAKE the
# index lock and could only do it by building an argv and calling `main()` through
# `_panel_write._lockmod()` — a dependency `_deps` attributed to the panel, so it
# was never visible as `audit-task -> audit-lock` at all.
def cmd_acquire(args, out):
    return _locks.acquire(args.project, args.name, note=args.note,
                          takeover=args.takeover, session=args.session,
                          pid=args.pid, out=out)


def cmd_release(args, out):
    return _locks.release(args.project, args.name, session=args.session,
                          pid=args.pid, force=args.force, out=out)


def cmd_status(args, out):
    rows = collect(args.project)
    if args.json:
        out(json.dumps({"locks": rows}, indent=2, sort_keys=True))
        return 0
    if not rows:
        out("[audit-lock] no locks held")
        return 0
    out("[audit-lock] %d lock(s)" % len(rows))
    for r in rows:
        out("  %-22s %-11s %s" % (r["name"], "LIVE" if r["live"] else "abandoned",
                                  r["info"].get("note") or ""))
        out("  %-22s %s" % ("", r["basis"]))
    return 0


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-lock.py", add_help=True)
    p.add_argument("command", choices=["acquire", "release", "status"])
    p.add_argument("name", nargs="?", default="index")
    p.add_argument("--project", default=".")
    p.add_argument("--note", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--pid", default=None)
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        if args.command == "acquire":
            return cmd_acquire(args, out)
        if args.command == "release":
            return cmd_release(args, out)
        return cmd_status(args, out)
    except Exception as exc:                        # never leave a caller guessing
        out("[audit-lock] internal error: %s" % exc)
        return E_ERR


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to main(), which would read the
        # flag as a command name. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-lock.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_lock.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
