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
import calendar
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

STALE_MINUTES = 60          # only consulted when liveness is unknowable
E_LIVE, E_STALE, E_USAGE, E_ERR = 3, 4, 2, 1


# --- liveness -----------------------------------------------------------------
def pid_alive(pid):
    """True / False / None (unknown). None is the caller's cue to fall back to age.

    NOT os.kill(pid, 0) on Windows: CPython implements os.kill there as
    OpenProcess + TerminateProcess(handle, sig), so signal 0 would TERMINATE the
    process it was asked about -- with exit code 0, invisibly. CI runs
    windows-latest, so this is a probe that had to be written per platform.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True             # exists, owned by another user
    except Exception:
        return None


def _pid_alive_windows(pid):
    """OpenProcess(SYNCHRONIZE) + WaitForSingleObject: signalled means exited."""
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        SYNCHRONIZE, ERROR_ACCESS_DENIED, WAIT_TIMEOUT = 0x00100000, 5, 0x00000102
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == WAIT_TIMEOUT
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        return None


def _age_minutes(info, path):
    """Minutes since the lock was taken -- from `startedAt`, else the file mtime.

    calendar.timegm, not time.mktime: `startedAt` is UTC, and mktime reads a
    struct_time as LOCAL time. Correcting that with time.timezone is wrong by an
    hour under DST (time.altzone is the summer offset), and the whole comparison
    is against a 60-minute threshold -- so the error and the threshold are the
    same size. CI runners are UTC, where a local-time bug is invisible; the user
    in CEST is the one it would bite. Keep local time out of it entirely.
    """
    started = (info or {}).get("startedAt")
    if started:
        try:
            t = time.strptime(str(started), "%Y-%m-%dT%H:%M:%SZ")
            return (time.time() - calendar.timegm(t)) / 60.0
        except Exception:
            pass
    try:
        return (time.time() - os.path.getmtime(path)) / 60.0
    except OSError:
        return 0.0


def judge(info, path, host=None):
    """Is this lock held by a live run? -> (live: bool, basis: str).

    `basis` is the sentence that makes the verdict checkable -- every claim this
    plugin prints carries the thing that makes it true, and "another session
    holds this" is a claim the human is about to act on.
    """
    host = host or platform.node()
    info = info if isinstance(info, dict) else {}
    pid, lock_host = info.get("pid"), info.get("hostname")
    age = _age_minutes(info, path)
    if pid and lock_host == host:
        alive = pid_alive(pid)
        if alive is True:
            return True, "pid %s is running on this host (%s)" % (pid, host)
        if alive is False:
            return False, "pid %s is gone on this host (%s)" % (pid, host)
        basis = "pid %s on this host could not be probed" % pid
    elif pid:
        basis = "held by %s, not this host" % (lock_host or "an unknown host")
    else:
        basis = "no pid recorded (taken before liveness checks, or by hand)"
    fresh = age < STALE_MINUTES
    return fresh, "%s; %s %.0f min old, threshold %d" % (
        basis, "taken" if fresh else "last touched", age, STALE_MINUTES)


# --- paths --------------------------------------------------------------------
def lock_dir(project):
    """$(git -C <project> rev-parse --git-common-dir)/audit-locks.

    The shared git dir, so the locks span every worktree of one clone and never
    show up in `git status`. None when this is not a git repo.
    """
    try:
        out = subprocess.run(["git", "-C", project, "rev-parse", "--git-common-dir"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=15)
        if out.returncode != 0:
            return None
        common = out.stdout.decode("utf-8", "replace").strip()
        if not common:
            return None
        if not os.path.isabs(common):
            common = os.path.join(project, common)
        return os.path.join(os.path.realpath(common), "audit-locks")
    except Exception:
        return None


def valid_name(name):
    """`index` or `phase-<id>`; the id is restricted so it cannot escape the dir."""
    if name == "index":
        return True
    if not name.startswith("phase-"):
        return False
    rest = name[len("phase-"):]
    return bool(rest) and all(c.isalnum() or c in "._-" for c in rest)


def read_lock(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _identity(args):
    """What goes into the lock: whose run this is, and a pid that outlives us."""
    sid = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    pid = args.pid or os.environ.get("CLAUDE_PID") or None
    try:
        pid = int(pid) if pid else None
    except (TypeError, ValueError):
        pid = None
    return sid, pid


def _write_lock(path, info):
    """Write via a sibling temp + os.replace, so a reader never sees half a lock."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".lock-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- commands -----------------------------------------------------------------
def cmd_acquire(args, out):
    ld = lock_dir(args.project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % args.project)
        return E_ERR
    if not valid_name(args.name):
        out("[audit-lock] bad lock name %r -- expected `index` or `phase-<id>`" % args.name)
        return E_USAGE
    try:
        os.makedirs(ld, exist_ok=True)
    except OSError as exc:
        out("[audit-lock] cannot create %s: %s" % (ld, exc))
        return E_ERR

    sid, pid = _identity(args)
    info = {"hostname": platform.node(),
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": args.note or args.name}
    if pid:
        info["pid"] = pid
    if sid:
        info["sessionId"] = sid

    path = os.path.join(ld, args.name + ".lock")
    try:                        # O_EXCL: the create IS the test, with no window
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        out("[audit-lock] acquired %s%s" % (args.name, "" if pid else
                                            " (no pid recorded -- age rule applies)"))
        return 0
    except FileExistsError:
        pass

    held = read_lock(path)
    live, basis = judge(held, path)
    who = held.get("sessionId") or held.get("hostname") or "an unknown session"
    what = held.get("note") or args.name
    if live and not args.takeover:
        out("[audit-lock] %s is HELD by a live run -- %s" % (args.name, who))
        out("             doing: %s" % what)
        out("             basis: %s" % basis)
        out("             Stop. Do not take this over; wait for it or ask its owner.")
        return E_LIVE
    if not live and not args.takeover:
        out("[audit-lock] %s looks abandoned -- %s" % (args.name, who))
        out("             doing: %s" % what)
        out("             basis: %s" % basis)
        out("             Confirm with the human, then rerun with --takeover.")
        return E_STALE
    try:
        info["takenOverFrom"] = {k: held.get(k) for k in
                                 ("sessionId", "hostname", "pid", "startedAt", "note")
                                 if held.get(k) is not None}
        info["takenOverBasis"] = basis
        _write_lock(path, info)
    except Exception as exc:
        out("[audit-lock] takeover failed: %s" % exc)
        return E_ERR
    out("[audit-lock] took over %s from %s" % (args.name, who))
    out("             basis: %s" % basis)
    if live:
        out("             WARNING: that run looked LIVE. Both sessions may now write.")
    return 0


def cmd_release(args, out):
    ld = lock_dir(args.project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % args.project)
        return E_ERR
    if not valid_name(args.name):
        out("[audit-lock] bad lock name %r" % args.name)
        return E_USAGE
    path = os.path.join(ld, args.name + ".lock")
    if not os.path.exists(path):
        out("[audit-lock] %s was not held -- nothing to release" % args.name)
        return 0
    held = read_lock(path)
    sid, _pid = _identity(args)
    owner = held.get("sessionId")
    # Releasing a lock that is no longer yours is how a session that was taken
    # over finds out -- today it deletes the winner's lock and neither ever knows.
    if owner and sid and owner != sid and not args.force:
        out("[audit-lock] %s is NOT yours to release -- held by %s" % (args.name, owner))
        out("             You were taken over. Anything you wrote since may have")
        out("             raced that session. Re-read the shard before trusting it.")
        if held.get("takenOverFrom", {}).get("sessionId") == sid:
            out("             (this lock records taking over from you)")
        return E_LIVE
    try:
        os.unlink(path)
    except OSError as exc:
        out("[audit-lock] cannot remove %s: %s" % (path, exc))
        return E_ERR
    out("[audit-lock] released %s" % args.name)
    return 0


def collect(project):
    """[{name, live, basis, info}] for every lock held, newest note first."""
    ld = lock_dir(project)
    rows = []
    if not ld or not os.path.isdir(ld):
        return rows
    try:
        names = sorted(n for n in os.listdir(ld) if n.endswith(".lock"))
    except OSError:
        return rows
    for n in names:
        path = os.path.join(ld, n)
        info = read_lock(path)
        live, basis = judge(info, path)
        rows.append({"name": n[:-len(".lock")], "live": live,
                     "basis": basis, "info": info})
    return rows


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
