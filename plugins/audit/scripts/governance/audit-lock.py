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
                               [--wait SECONDS]
  audit-lock.py release <name> [--project DIR] [--force]
  audit-lock.py status         [--project DIR] [--json]

This module carries no inline `--selftest` any more; its cases live in
`plugins/audit/tests/test_audit_lock.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The flag is still accepted and still exits
0, pointing there.

  <name> is `phase-<phaseId>` or one of `_locks.FIXED_NAMES` -- `index` for a
  structural write, `usage` for the ledger backfill. `_locks.valid_name` is what
  decides, so a name listed there is a name this command accepts.
  --session / --pid override the identity written into the lock; they default to
  $CLAUDE_CODE_SESSION_ID and $CLAUDE_PID.
  --wait says how long a LIVE holder is waited out before the refusal is printed.
  It defaults to `_locks.WAIT_SECONDS`, and zero refuses the instant the name
  exists -- which is what this command did before executors ran side by side.

Exit codes:
  0  acquired / released / status printed / already held by this run
  3  held by a LIVE run -- refuse and stop
  4  held by a run that is NOT alive -- rerun with --takeover to seize it
  2  usage error
  1  internal error

`already held by this run` is `_locks.E_OURS` collapsed onto 0 by `shell_code`,
at the PROCESS boundary and nowhere earlier: a shell reads this command as pass
or fail, while an in-process caller reads `main()`'s return and has to tell a
lock it was HANDED from one it TOOK. The line printed above the status is what
says not to give it back -- the part a status cannot carry.

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

An EMPTY claim is the one thing that reads dead, and it is not a tie: a file with
no record in it names nobody, so there is no holder the bias could protect. It is
a take that was interrupted before it recorded itself, it is offered for takeover
like any other run that is not there, and `_locks._interrupted_take()` is where
that is decided. Anything present but unparseable stays LIVE -- something wrote it.

A pid can be reused by an unrelated process, which reads as LIVE -- the same safe
direction. WHICH pid is recorded is the holder's question rather than a constant:
this script's pid dies the instant it exits, so what it writes is the run that
invoked it (the orchestrator's own, via $CLAUDE_PID), and with no durable pid
available it records none and stays on the age rule rather than inventing
liveness. A caller that takes the lock and gives it back inside one process is
the holder itself and records that, which is what makes a killed run's claim read
dead the moment the run stops; `_locks._holder_pid` is where the two part.

Acquire is also race-free: the claim is written into a sibling and then linked
onto its real name, and the LINK is what refuses a name already taken. That
replaces the prose's "if the file exists ... else write it", which had a window
between the two, and it closes the second window the exclusive create left --
the one between creating the claim and describing it, where a killed run used to
strand a file naming nobody.

And a lock that cannot be written is reported as that, never as a lock that is
HELD: the claim is a coordination advisory, so failing to write one refuses the
lock and not the work, and the caller reads the exit code below rather than
catching an exception.
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
# The re-entry answer, re-exported for the reason the four above are: the panel
# takes this lock through `main()`, and telling a lock it was HANDED from one it
# TOOK is what stands between it and giving back somebody else's hold.
E_OURS = _locks.E_OURS


# --- commands -----------------------------------------------------------------
# Three adapters and an argument parser: that is all this file is now. Each turns
# an argparse Namespace into a call on `_locks`, which is where every one of these
# bodies used to live inline. They moved because `audit-task.py` needs to TAKE the
# index lock and could only do it by building an argv and calling `main()` through
# an accessor the panel published for READING one — a dependency `_deps` attributed
# to the panel, so it was never visible as `audit-task -> audit-lock` at all, and
# an accessor that answers with the library has no `main` to be reached through.
# Every taker imports the library now, and that accessor is gone from the write
# path it was being borrowed by.
def cmd_acquire(args, out):
    # HANDED OFF BY CONSTRUCTION. This process exits the moment it has the lock,
    # so the holder is the run that invoked it and the claim records that run's
    # identity -- recording this one's would leave a lock whose holder is gone
    # before the next command starts.
    #
    # THE ANSWER IS PASSED THROUGH WHOLE, including `E_OURS`. `shell_code` is
    # where it becomes a process status, and the distance between the two is
    # deliberate: an in-process caller reads what this returns.
    return _locks.acquire(args.project, args.name, note=args.note,
                          takeover=args.takeover, session=args.session,
                          pid=args.pid, wait=args.wait, handed_off=True, out=out)


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


def shell_code(code):
    """The PROCESS status for an answer -> `E_OURS` reads as 0, everything else stands.

    A SHELL READS THIS COMMAND AS PASS OR FAIL, and "you already have it" is not a
    failure to take it: the step may proceed, which is what exit 0 means to every
    caller of this command, and a fifth status would be read as a refusal by every
    `if` already written against the table in the module docstring.

    The collapse lives HERE rather than in `cmd_acquire` because the two callers
    are not asking the same question. A shell asks whether it may go on; an
    in-process caller -- the panel takes this lock through `main()` -- asks that
    AND whether the lock is its own to give back, and an answer collapsed before
    it arrives is how a caller comes to release a hold that is still in use. The
    line the library printed above the status carries the rest.
    """
    return 0 if code == E_OURS else code


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-lock.py", add_help=True)
    p.add_argument("command", choices=["acquire", "release", "status"])
    p.add_argument("name", nargs="?", default="index")
    p.add_argument("--project", default=".")
    p.add_argument("--note", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--pid", default=None)
    p.add_argument("--wait", type=float, default=None)
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
    sys.exit(shell_code(main(sys.argv[1:])))
