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
  audit-lock.py --selftest

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


# --- selftest -----------------------------------------------------------------
def _selftest():
    import shutil
    results = []

    def check(name, cond):
        results.append(bool(cond))
        print("%s %s" % ("PASS" if cond else "FAIL", name))

    def run(argv, project):
        lines = []
        code = main(argv + ["--project", project], out=lines.append)
        return code, "\n".join(lines)

    # A pid that is definitely gone: spawn one and wait for it.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    dead_pid = dead.pid

    # (l) liveness probe
    check("l1 our own pid reads alive", pid_alive(os.getpid()) is True)
    check("l2 an exited pid reads dead", pid_alive(dead_pid) is False)
    check("l3 pid 0 is unknowable, not a verdict", pid_alive(0) is None)
    check("l4 garbage pid is unknowable", pid_alive("nope") is None)

    # (j) judge -- the whole point: liveness beats age in both directions
    here = platform.node()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 95 * 60))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    live, basis = judge({"hostname": here, "pid": os.getpid(), "startedAt": old}, "")
    check("j1 a 95-min run with a live pid is LIVE (false stale fixed)", live is True)
    check("j1b and says why", "is running on this host" in basis)
    live, basis = judge({"hostname": here, "pid": dead_pid, "startedAt": now}, "")
    check("j2 a 1-min run with a dead pid is stale at once (false fresh fixed)",
          live is False)
    check("j2b and says why", "is gone on this host" in basis)
    live, basis = judge({"hostname": here, "startedAt": old}, "")
    check("j3 no pid -> the old age rule, and it says so", live is False)
    check("j3b basis names the threshold", "threshold 60" in basis)
    live, _ = judge({"hostname": here, "startedAt": now}, "")
    check("j4 no pid, young -> live", live is True)
    live, basis = judge({"hostname": "somewhere-else", "pid": os.getpid(),
                         "startedAt": now}, "")
    check("j5 another host's pid is not probed", live is True and "not this host" in basis)
    live, _ = judge({"hostname": "somewhere-else", "pid": os.getpid(),
                     "startedAt": old}, "")
    check("j5b another host falls back to age", live is False)
    # j6 used `__file__` as "a file with a recent mtime", so it only passed on a day
    # someone edited audit-lock.py — it went red the first time the full suite ran
    # against an unmodified checkout. A test whose verdict depends on the clock
    # relative to a source file's mtime asserts nothing you can rely on.
    _fd, _mt = tempfile.mkstemp(prefix="audit-lock-mtime-")
    os.close(_fd)
    check("j6 an unreadable lock with a fresh file is not a licence to seize it",
          judge({}, _mt)[0] is True)
    os.utime(_mt, (time.time() - 95 * 60, time.time() - 95 * 60))
    check("j6b an unreadable lock falls back to the file's own age",
          judge({}, _mt)[0] is False)
    os.unlink(_mt)
    check("j6c and a lock whose file is gone reads live, never seizable",
          judge({}, os.path.join(tempfile.gettempdir(), "no-such.lock"))[0] is True)

    # (a) age math -- the number the whole threshold rests on. Pinned in a
    # non-UTC, DST-observing zone too: CI runners are UTC, so a local-time bug
    # would pass there and be exactly 60 minutes wrong for a user in Europe.
    def age_cases(label):
        for mins in (0, 30, 59, 61, 95, 1440):
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                  time.gmtime(time.time() - mins * 60))
            got = _age_minutes({"startedAt": stamp}, "")
            check("a%d %s: %d min old measures as %d" % (mins, label, mins, mins),
                  abs(got - mins) < 1)
    age_cases("UTC-agnostic")
    _tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Belgrade"        # UTC+1, UTC+2 under DST
        if hasattr(time, "tzset"):
            time.tzset()
            age_cases("in CET/CEST")
        else:
            print("SKIP a* in CET/CEST (no time.tzset on this platform)")
    finally:
        if _tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = _tz
        if hasattr(time, "tzset"):
            time.tzset()
    check("a-mtime falls back to the file when startedAt is missing or junk",
          _age_minutes({"startedAt": "not a date"}, __file__) > 0)

    # (n) name validation -- a lock name reaches the filesystem
    check("n1 index", valid_name("index"))
    check("n2 phase-P1", valid_name("phase-P1"))
    check("n3 traversal rejected", not valid_name("phase-../../etc/passwd"))
    check("n4 separator rejected", not valid_name("phase-a/b"))
    check("n5 bare id rejected", not valid_name("P1"))
    check("n6 empty phase id rejected", not valid_name("phase-"))

    # (c) the CLI, against a real git repo
    tmp = tempfile.mkdtemp(prefix="audit-lock-")
    try:
        if not shutil.which("git"):
            print("SKIP c* (git not installed)")
        else:
            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ld = lock_dir(tmp)
            check("c0 lock dir resolves inside the git dir",
                  ld and ld.endswith("audit-locks") and ".git" in ld)

            code, txt = run(["acquire", "phase-P1", "--note", "phase P1",
                             "--session", "sess-A", "--pid", str(os.getpid())], tmp)
            check("c1 first acquire succeeds", code == 0 and "acquired" in txt)
            check("c1b lock records the pid it was given",
                  read_lock(os.path.join(ld, "phase-P1.lock")).get("pid") == os.getpid())

            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c2 a live holder refuses (exit 3)", code == E_LIVE)
            check("c2b and names the holder", "sess-A" in txt)
            check("c2c and does not offer a takeover", "--takeover" not in txt)

            code, txt = run(["acquire", "index", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c3 a different lock is free (two phases run in parallel)", code == 0)
            code, _ = run(["release", "index", "--session", "sess-B"], tmp)
            check("c3b released", code == 0)

            # Age alone must not unlock a live run -- the C1 defect, end to end.
            p1 = os.path.join(ld, "phase-P1.lock")
            info = read_lock(p1)
            info["startedAt"] = old
            _write_lock(p1, info)
            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c4 a 95-min-old LIVE run still refuses", code == E_LIVE)

            info["pid"] = dead_pid
            _write_lock(p1, info)
            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c5 a dead holder offers takeover (exit 4)", code == E_STALE)
            check("c5b and says how", "--takeover" in txt)
            check("c5c but has not seized it yet",
                  read_lock(p1).get("sessionId") == "sess-A")

            code, txt = run(["acquire", "phase-P1", "--session", "sess-B", "--takeover",
                             "--pid", str(os.getpid())], tmp)
            check("c6 --takeover seizes it", code == 0 and "took over" in txt)
            after = read_lock(p1)
            check("c6b now owned by B", after.get("sessionId") == "sess-B")
            check("c6c and records who it took from",
                  after.get("takenOverFrom", {}).get("sessionId") == "sess-A")

            # The loser learns it lost -- today it silently deletes the winner's lock.
            code, txt = run(["release", "phase-P1", "--session", "sess-A"], tmp)
            check("c7 the taken-over session cannot release (exit 3)", code == E_LIVE)
            check("c7b and is told it was taken over", "taken over" in txt)
            check("c7c the winner's lock survives", os.path.exists(p1))

            code, txt = run(["status"], tmp)
            check("c8 status lists it", "phase-P1" in txt and "LIVE" in txt)
            code, txt = run(["status", "--json"], tmp)
            check("c8b --json parses", json.loads(txt)["locks"][0]["name"] == "phase-P1")
            check("c8c and carries the basis", json.loads(txt)["locks"][0]["basis"])

            code, _ = run(["release", "phase-P1", "--session", "sess-B"], tmp)
            check("c9 the owner releases", code == 0)
            check("c9b lock is gone", not os.path.exists(p1))
            code, txt = run(["release", "phase-P1", "--session", "sess-B"], tmp)
            check("c9c releasing twice is not an error", code == 0)

            code, txt = run(["acquire", "phase-../escape", "--session", "s"], tmp)
            check("c10 a traversing name is a usage error", code == E_USAGE)

            # A lock written by the old prose (no pid) must still work.
            _write_lock(p1, {"hostname": here, "startedAt": now, "note": "legacy"})
            code, _ = run(["acquire", "phase-P1", "--session", "sess-C"], tmp)
            check("c11 a legacy pid-less lock is honoured", code == E_LIVE)
            _write_lock(p1, {"hostname": here, "startedAt": old, "note": "legacy"})
            code, _ = run(["acquire", "phase-P1", "--session", "sess-C"], tmp)
            check("c11b and goes stale on age, as it always did", code == E_STALE)
            code, _ = run(["release", "phase-P1", "--session", "sess-C", "--force"], tmp)
            check("c11c --force releases someone else's lock", code == 0)

            # No pid available at all: record none rather than invent liveness.
            env = dict(os.environ)
            env.pop("CLAUDE_PID", None)
            saved = os.environ.pop("CLAUDE_PID", None)
            try:
                code, txt = run(["acquire", "phase-P9", "--session", "s"], tmp)
                check("c12 acquiring without a pid says the age rule applies",
                      code == 0 and "age rule" in txt)
                check("c12b and records no pid",
                      "pid" not in read_lock(os.path.join(ld, "phase-P9.lock")))
            finally:
                if saved is not None:
                    os.environ["CLAUDE_PID"] = saved

        code, _ = run(["status"], os.path.join(tmp, "not-a-repo"))
        check("c13 status outside a repo is quiet, not an error", code == 0)
        code, txt = run(["acquire", "index"], os.path.join(tmp, "not-a-repo"))
        check("c13b acquire outside a repo errors clearly",
              code == E_ERR and "not a git repository" in txt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # argparse writes its usage text to stderr on an invalid choice; swallow it so
    # a passing suite prints only its own lines.
    import contextlib
    with open(os.devnull, "w") as _null, contextlib.redirect_stderr(_null):
        _rc = main(["frobnicate"], out=lambda *_: None)
    check("m1 an unknown command is a usage error", _rc == E_USAGE)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
