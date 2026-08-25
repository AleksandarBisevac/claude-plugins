#!/usr/bin/env python3
"""
Where a lock lives, what its name may be, and whether the run holding it is alive.

The READ half of the /audit concurrency lock. `audit-lock.py` is the command that
takes and releases one; everything that only ever ASKS about a lock asks here.
That is most of the callers: `_panel_state` badges a lock in the panel,
`audit-doctor` lists what is held, `audit-usage` decides whether a backfill would
collide, and `hooks/_config.py` answers "is someone else writing this shard"
on tool calls.

WHY IT IS ITS OWN MODULE. Those three scripts each reached the verdict by loading
`audit-lock.py` through `_loader`, and `_deps.layer_violations()` reads a
`_loader` call as a real edge — so `_panel_state` (L5) and two L7 commands
pointing at an L7 entry point were three of the seventeen entries in
`KNOWN_LAYER_DEBT`. A liveness rule four callers share is not an entry point's
private business; it belongs at the bottom of the graph where all four can import
it, which is layer 1. Moving the CALL into a new module that then loaded
`audit-lock.py` would have hidden those edges rather than retired them.

THE VERDICT'S BIAS IS THE LOAD-BEARING PART, AND IT IS NOT SYMMETRIC. Every
uncertainty resolves to LIVE. A false "dead" means two writers and a silently
corrupted shard; a false "alive" means a refusal a human clears by deleting one
file, which `/audit:doctor` already explains. `audit-lock.py`'s own docstring
carries the full argument for liveness-over-age, including why the 60-minute rule
was wrong in BOTH directions and why `os.kill(pid, 0)` cannot be used on Windows.

`judge()` returns a BASIS beside every verdict, never a bare boolean: "another
session holds this" is a claim a human is about to act on, and the sentence that
makes it checkable is the difference between a lock and a superstition.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__locks.py` — see `plugins/audit/tests/_harness.py`.
"""
import calendar
import json
import os
import platform
import subprocess
import sys
import tempfile
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

STALE_MINUTES = 60          # only consulted when liveness is unknowable
# The exit codes `acquire`/`release` answer with. They live here rather than in
# `audit-lock.py` because they are the CONTRACT of those two functions, and
# `audit-task.py` branches on them - a caller that must read a code cannot be
# made to import a command to find out what it means.
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


def _identity(session, pid):
    """What goes into the lock: whose run this is, and a pid that outlives us."""
    sid = session or os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    pid = pid or os.environ.get("CLAUDE_PID") or None
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


# --- taking and giving back ----------------------------------------------------
# `acquire` and `release` take plain arguments rather than an argparse Namespace,
# and that is the whole reason they could move. They were `cmd_acquire(args, out)`
# and `cmd_release(args, out)` in `audit-lock.py`, which meant the only way for
# another module to TAKE a lock was to build an argv and call that command's
# `main()` — which is exactly what `audit-task.py` does through
# `_panel_write._lockmod()`. `_deps` could not see that edge (the literal sits in
# `_panel_state`, so the graph blamed the panel) and it was real all the same: a
# hidden dependency is not a retired one. Both are functions here, `audit-lock.py`
# wraps them for the CLI, and every caller that needs to acquire says so in an
# import that the layer lint can read.
def held(code):
    """True when an `acquire` return value means the lock IS held.

    F188. `acquire` returns an INT on every path - 0 held, `E_ERR` / `E_USAGE` /
    `E_LIVE` / `E_STALE` otherwise - and two callers tested it with
    `isinstance(handle, dict)`, which is never true of an int. Both defects follow
    from that one misreading and the `try/finally` around it made the first look
    handled: the release never ran, so every proposal write left the index lock on
    disk; and the status was never read, so a refused acquire fell straight into
    the write and changed the manifest with NO LOCK HELD - the exact case the lock
    exists for.

    Published as a function rather than left as `code == 0` at each call site
    because what went wrong was a caller inventing its own reading of this
    contract. There is one reading now and it lives with the contract.
    """
    return code == 0


def available(project):
    """True when this project has a lock scheme at all.

    THE THIRD ANSWER, and leaving it out re-broke the panel. `acquire` returns
    `E_ERR` both for "not a git repository" - where there is no lock to take and
    never was - and for a real failure creating the directory. A caller that
    refuses to write on every non-zero code therefore refuses in a project with no
    `.git`, which is a case the panel has a documented fallback for: it drops to a
    working-tree lockfile and proceeds under the weaker guarantee.

    So the question is asked BEFORE acquiring, where it has an unambiguous answer,
    rather than inferred afterwards from a code that means two things. Found by the
    browser gate: the F188 repair, correct for a contended lock, made every
    proposal write in a non-git fixture refuse.
    """
    return bool(lock_dir(project))


def refusal(code, name):
    """One line for a caller that could not take `name`, safe to put in a payload.

    THE TERMINAL LINES ARE NOT THIS. `acquire` writes a verdict plus indented
    detail through `out`, and that detail names the HOST the live pid runs on and,
    on two paths, an absolute project directory. Those lines are for a terminal
    the operator is already sitting at. A caller that hands them to a structured
    `findings` list publishes them: the panel paints proposal findings, so the
    first draft of the F188 repair moved a hostname onto an HTTP response - the
    same class of leak the machine-identity release existed to close.

    So the caller gets a sentence with no host and no path, and the detail stays
    where it was already going. `/audit:lock status` is the door for "who holds
    it", and it names itself here rather than leaving the reader to look.
    """
    if code == E_LIVE:
        return ("the %s lock is held by a live run -- wait for it, or ask its "
                "owner; `audit-lock.py status` says who and since when" % (name,))
    if code == E_STALE:
        return ("the %s lock is STALE -- its run is gone. Confirm that, then "
                "retake it with --takeover" % (name,))
    if code == E_USAGE:
        return "the %s lock was asked for by a name it does not have" % (name,)
    return ("the %s lock could not be taken (exit %s) -- run `audit-lock.py "
            "status` for the reason" % (name, code))


def acquire(project, name, note=None, takeover=False, session=None, pid=None,
            out=print):
    ld = lock_dir(project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % project)
        return E_ERR
    if not valid_name(name):
        out("[audit-lock] bad lock name %r -- expected `index` or `phase-<id>`" % name)
        return E_USAGE
    try:
        os.makedirs(ld, exist_ok=True)
    except OSError as exc:
        out("[audit-lock] cannot create %s: %s" % (ld, exc))
        return E_ERR

    sid, pid = _identity(session, pid)
    info = {"hostname": platform.node(),
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": note or name}
    if pid:
        info["pid"] = pid
    if sid:
        info["sessionId"] = sid

    path = os.path.join(ld, name + ".lock")
    try:                        # O_EXCL: the create IS the test, with no window
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        out("[audit-lock] acquired %s%s" % (name, "" if pid else
                                            " (no pid recorded -- age rule applies)"))
        return 0
    except FileExistsError:
        pass

    held = read_lock(path)
    live, basis = judge(held, path)
    who = held.get("sessionId") or held.get("hostname") or "an unknown session"
    what = held.get("note") or name
    if live and not takeover:
        out("[audit-lock] %s is HELD by a live run -- %s" % (name, who))
        out("             doing: %s" % what)
        out("             basis: %s" % basis)
        out("             Stop. Do not take this over; wait for it or ask its owner.")
        return E_LIVE
    if not live and not takeover:
        out("[audit-lock] %s looks abandoned -- %s" % (name, who))
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
    out("[audit-lock] took over %s from %s" % (name, who))
    out("             basis: %s" % basis)
    if live:
        out("             WARNING: that run looked LIVE. Both sessions may now write.")
    return 0


def release(project, name, session=None, pid=None, force=False, out=print):
    ld = lock_dir(project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % project)
        return E_ERR
    if not valid_name(name):
        out("[audit-lock] bad lock name %r" % name)
        return E_USAGE
    path = os.path.join(ld, name + ".lock")
    if not os.path.exists(path):
        out("[audit-lock] %s was not held -- nothing to release" % name)
        return 0
    held = read_lock(path)
    sid, _pid = _identity(session, pid)
    owner = held.get("sessionId")
    # Releasing a lock that is no longer yours is how a session that was taken
    # over finds out -- today it deletes the winner's lock and neither ever knows.
    if owner and sid and owner != sid and not force:
        out("[audit-lock] %s is NOT yours to release -- held by %s" % (name, owner))
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
    out("[audit-lock] released %s" % name)
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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_locks.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__locks.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
