#!/usr/bin/env python3
"""
Where a lock lives, what its name may be, and whether the run holding it is alive.

EVERY LOCK THIS PRODUCT TAKES IS TAKEN HERE. `acquire` and `release` below are
the only implementation; `audit-lock.py` wraps them for a shell, the panel's
write path and the manifest commands call them in process, and the usage
backfill takes the name it guards the monthly ledger files with. Everything that
only ever ASKS about a lock asks here too -- `_panel_state` badges one in the
panel, `audit-doctor` lists what is held, and `hooks/_config.py` answers "is
someone else writing this shard" on tool calls.

The journal's per-file append lock is the one deliberate exception, and it is a
different resource: it serializes two writers of ONE file's tail inside the
working tree, for as long as one append takes, and declines rather than waits.
`_journal_io` carries why.

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

AN EMPTY CLAIM IS NOT AN UNCERTAINTY, WHICH IS WHY IT IS THE ONE THING THAT READS
DEAD. A file with no record in it names no session, no pid and no start, so there
is no holder for the bias to be protecting -- it is a take that was interrupted
before it said who it was, and `_interrupted_take()` grades it as that instead of
making every run on the machine wait out a threshold on its behalf. Anything
present but unparseable stays LIVE: something wrote it.

`judge()` returns a BASIS beside every verdict, never a bare boolean: "another
session holds this" is a claim a human is about to act on, and the sentence that
makes it checkable is the difference between a lock and a superstition.

A CONTENDED LOCK IS WAITED OUT BEFORE IT IS REFUSED, and that bound is the whole
of the concession. Refusing the instant the name exists is the right answer on a
machine running one command at a time; this product spawns executors in parallel
by design and the index lock is taken for a single structural write, so two of
those overlapping for as long as a file write takes turned ordinary parallelism
into a stopped command. `WAIT_SECONDS` is how much overlap is absorbed, `--wait`
and the `wait` argument move it, and a lock held for a whole phase run outlives
any bound and reaches the same refusal it always did.

A LOCK THIS RUN ALREADY HOLDS IS ANSWERED, NEVER WAITED FOR. `held_by_us()` has
been able to say so since the day a hand-held index lock refused the operator who
was holding it, and `acquire` never asked -- so a command that took a lock and
called another command that takes the same one was refused by its own claim, and
with a wait in front of that refusal it would have waited for itself. `E_OURS` is
that answer, and it is deliberately not `0`: the caller may proceed, and the
release at the end of its work would hand back a lock the outer hold still needs.
`held()` reads the first half of that, `took()` the second.

WHO COUNTS AS "THIS RUN" DEPENDS ON HOW THE CLAIM WAS TAKEN. The answer used to be
the session, because the flow it was built for is a lock taken by hand from a
shell and several commands run under it - and that same answer let parallel tool
calls of one session each re-enter a claim another of them had taken for its own
write, so every one wrote over the others and reported success. A claim a process
takes for its own write now carries a TOKEN, re-entered only by that process and
by a child that inherits the token through `TOKEN_ENV`; every other process waits,
session or not. A claim a server takes for one request is `perCall`: its token is
not carried, and no other call re-enters it, the threads beside it included. A claim taken by hand is recorded `handedOff`, and its session
still works under it, because that is the protocol the commands are written to.

THE PID IN A CLAIM IS THE ONE WHOSE DEATH ENDS THE HOLD. A caller that takes the
lock and gives it back before it returns is this process, so this process is what
gets recorded; a command that exits with the lock still held says so with
`handed_off` and records the run that invoked it. Recording the durable identity
for the first shape is what left a killed run holding a lock every gate on the
machine consults, with nothing dead for `judge` to find.

A TAKEOVER IS DECIDED BY THE CREATE, AND RECORDED ONLY WHERE IT DISPLACED
SOMETHING. Read, judge, then write leaves a window wide enough for another taker
to pass the same judgement, and the later write then replaced a claim that was by
then live -- the state this lock exists to make impossible, reached through the
door built for recovery. The judged claim is removed only while it is still that
claim, the exclusive create decides who gets the name, and the loser is told it
lost. What the row says is then bounded by what happened: a holder that let go on
its own was displaced by nobody.

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
# How long a LIVE holder is waited out before the refusal is printed, and how
# often the name is re-asked inside that window. The bound covers a lock taken
# for one structural write and nothing longer: a phase lock is held for a whole
# run, so waiting on one buys the caller the delay and then the same refusal.
# Zero is the old behaviour, and is what a caller passes to read a refusal at once.
WAIT_SECONDS = 5.0
POLL_SECONDS = 0.05
# The exit codes `acquire`/`release` answer with. They live here rather than in
# `audit-lock.py` because they are the CONTRACT of those two functions, and
# `audit-task.py` branches on them - a caller that must read a code cannot be
# made to import a command to find out what it means.
E_LIVE, E_STALE, E_USAGE, E_ERR = 3, 4, 2, 1
# The answer for a caller that already holds what it asked for. HELD, so the work
# may proceed; not `0`, because the claim is not this call's to give back and a
# caller that released on it would drop the lock out from under the hold that is
# still using it.
E_OURS = 5
# The environment variable a holder's tokens travel to its children in: one token
# per claim this process took, separated by spaces. A child inherits it through
# the ordinary environment, which is what makes "a verb's own subprocess" a fact
# the lock can check rather than a guess from a shared session id.
TOKEN_ENV = "AUDIT_LOCK_TOKENS"


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


def _interrupted_take(info, path):
    """True when the claim at `path` carries no record at all -- an empty file.

    AN EMPTY CLAIM IS A TAKE THAT DID NOT FINISH, NOT A RUN TO WAIT FOR. It names
    no session, no pid and no start, so the identity rules have nothing to read
    and the age rule answers instead -- and answering LIVE there holds a lock
    every run on this machine consults, for as long as the threshold says, on
    behalf of a run that never recorded itself. The one thing that tells this
    apart from a lock somebody wrote by hand is that a hand-written one has
    something in it; zero bytes is the signature of a create whose write never
    came.

    This is the ONLY uncertainty that resolves away from LIVE, and it is not an
    exception to the bias: there is no holder to protect. Anything present but
    unparseable stays live, because something wrote it.
    """
    if info:
        return False
    try:
        return os.path.getsize(path) == 0
    except OSError:
        return False            # no file, or none that can be asked: unchanged


def _claim_holder(info, path):
    """One phrase for whoever left this claim, for a line a human will act on.

    An empty claim names nobody, and calling that "an unknown session" invents a
    run for the reader to go looking for -- the same mistake in the same
    direction as reporting a lock that could not be taken as one that is held.
    """
    return (info.get("sessionId") or info.get("hostname")
            or ("a take that did not finish recording itself"
                if _interrupted_take(info, path) else "an unknown session"))


def holder_gone(info, path=None, host=None):
    """True only where the END of the claim's run was observed.

    Two observations count: an empty claim file at `path` (`_interrupted_take`),
    and a recorded pid that is gone on the host the claim names, when that host is
    this one. Every other not-live reading - no pid, another host, a probe that
    answered nothing, an old claim - is an uncertainty, and those resolve to live.

    THE ONE PREDICATE for that question. `judge`, the release conflict and every
    caller deciding whether a holder may be replaced read it here, so "gone"
    cannot mean one thing to the verdict and another to the takeover.
    """
    info = info if isinstance(info, dict) else {}
    if path is not None and _interrupted_take(info, path):
        return True
    if not info:
        return False
    if str(info.get("hostname") or "") != (host or platform.node()):
        return False
    try:
        holder = int(info.get("pid"))
    except (TypeError, ValueError):
        return False
    return pid_alive(holder) is False


def judge(info, path, host=None):
    """Is this lock held by a live run? -> (live: bool, basis: str).

    `basis` is the sentence that makes the verdict checkable -- every claim this
    plugin prints carries the thing that makes it true, and "another session
    holds this" is a claim the human is about to act on.
    """
    host = host or platform.node()
    info = info if isinstance(info, dict) else {}
    if holder_gone(info, path, host):
        if _interrupted_take(info, path):
            return False, ("the claim file is empty -- a take was interrupted "
                           "before it recorded who took it, so there is no run "
                           "here to wait for")
        return False, "pid %s is gone on this host (%s)" % (info.get("pid"), host)
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


# The resources this directory coordinates under a FIXED name, beside the
# per-phase ones. Every taker of any of them comes through `acquire` below.
#
# `usage` guards the ledger backfill, and it is here for the reason `index` is:
# the backfill rewrites monthly ledger files, so two at once lose rows -- and it
# was taking a lock of its own shape in this same directory, asking whether the
# file was there, judging the holder, and then opening the path for writing.
# That is a read followed by a write, and it is exactly the window `_claim` was
# rebuilt to close. A lock the shared library does not issue is a lock nothing
# else can be refused by.
FIXED_NAMES = ("index", "usage")

# The namespace user tooling takes this directory's locks under -- an e2e guard
# driving one backend from several worktrees of one clone is the shape it is for.
# The prefix is what keeps it apart from the plugin's names: every reader that
# decides something from a name keys on `index`, `usage` or a `phase-` prefix, and
# none of them can match a name that begins with this one. `collect()` is the
# reader that lists EVERY name - `audit-lock.py status`, `/audit:status` and
# `/audit:doctor` show user locks beside the plugin's own, by name.
#
# A USER LOCK EXCLUDES BY HOLDER, NOT BY SESSION. Parallel subagents in different
# worktrees share one session id and one pid, so the re-entry answer the plugin's
# own names get would hand the second run a lock the first is still using; for a
# `user-` name a second acquire is refused like any other.
USER_PREFIX = "user-"
USER_NAME_MAX = 64
_USER_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# The rules, stated once: the refusal prints this and `commands/worktree.md`
# points at it. LOWER CASE ONLY because the lock directory sits on a
# case-folding filesystem by default on macOS and Windows, so
# two spellings differing in case would be two names and one file. NO DOT so a
# name cannot end in `.lock` and list as something it is not, and so no name
# reaches a filesystem that strips a trailing one.
USER_NAME_RULES = (
    "`user-<name>`, where <name> is 1-%d characters of a-z, 0-9, `-` and `_`, "
    "begins and ends with a letter or digit, and is not itself a lock name - "
    "not `index`, `usage`, `phase-<id>` or another `user-` name"
    % (USER_NAME_MAX,))


_ASCII_ID = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"


def is_plugin_name(name):
    """A name the plugin itself issues: one of `FIXED_NAMES`, or `phase-<id>`
    with the id restricted to ASCII `[A-Za-z0-9._-]` so it cannot escape the dir.

    ASCII, not `str.isalnum()`, which admits letters of every script - and a
    filesystem may normalise those, so two ids could meet in one file.
    """
    if name in FIXED_NAMES:
        return True
    if not name.startswith("phase-"):
        return False
    rest = name[len("phase-"):]
    return bool(rest) and all(c in _ASCII_ID for c in rest)


def is_user_name(name):
    """`user-<name>` under `USER_NAME_RULES`.

    The part after the prefix may not be a lock name in its own right. It could
    never EQUAL one -- the prefix sees to that -- but `user-index` would list as
    the index to anyone reading `status`, and that is the spoof this refuses.
    """
    if not name.startswith(USER_PREFIX):
        return False
    rest = name[len(USER_PREFIX):]
    if not rest or len(rest) > USER_NAME_MAX:
        return False
    if not all(c in _USER_ALPHABET or c in "-_" for c in rest):
        return False
    if rest[0] not in _USER_ALPHABET or rest[-1] not in _USER_ALPHABET:
        return False
    return not valid_name(rest)


def valid_name(name):
    """A name the plugin issues, or a user tool's `user-<name>`."""
    return is_plugin_name(name) or is_user_name(name)


def name_refusal(name):
    """The line a refused name gets, from acquire and release alike."""
    return ("[audit-lock] bad lock name %r -- expected one of %s, or `phase-<id>`,"
            " or for user tooling %s"
            % (name, ", ".join("`%s`" % (n,) for n in FIXED_NAMES),
               USER_NAME_RULES))


def _listed(ld, name):
    """Whether `name`'s own spelling is a file in `ld` - asked of the listing,
    because `os.path.exists` answers yes for a variant where case folds."""
    try:
        return (name + ".lock") in os.listdir(ld)
    except OSError:
        return False


def case_variant(ld, name):
    """A lock already in `ld` whose name differs from `name` only in case.

    On a case-folding filesystem - macOS and Windows by default - the two are one
    file, so `phase-P1` and `phase-p1` would share a claim there and not on
    Linux. Refusing the second spelling everywhere makes the answer the same on
    every platform. None when there is no such lock.
    """
    want = (name + ".lock").lower()
    try:
        names = os.listdir(ld)
    except OSError:
        return None
    for other in sorted(names):
        if other.lower() == want and other != name + ".lock":
            return other[:-len(".lock")]
    return None


def read_lock(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def held_by_us(info, session=None, pid=None):
    """`{"ours", "why"}` -- is this lock THIS session's own?

    `set-priority.py` once refused with exit 3 and `pid 80470 is running on this
    host` — and that pid was the operator, who had taken the index lock by hand
    around several structural writes, which is the flow the lock exists for. The
    documented workaround was "hold no lock by hand", i.e. do not use the thing.
    `release` has always answered this question (`is NOT yours to release`); only
    `acquire` never asked it.

    TWO SPELLINGS, EITHER SUFFICIENT, and `SECURITY.md` records why one is not
    enough: a lock taken from **Bash** carries `$CLAUDE_CODE_SESSION_ID`, while a
    hook is handed `session_id` in its payload and `$CLAUDE_PID` is a third name
    for the same run. Measured in a live session those are different values, so a
    run could lock as one identity and be refused as another — the gate denying
    the orchestrator its own bookkeeping. The tie goes to "ours": matching too
    eagerly costs a missed denial against a stranger who happens to share an id,
    and failing to match breaks the run that is holding the lock correctly.

    THAT RULE NOW COVERS ONLY A CLAIM TAKEN BY HAND, or one written before claims
    carried a token. A claim a process took for its own write is re-entered by
    its token alone - carried by the process and its children - and never across
    a session a caller names as different.

    A SESSION'S CLAIM WHOSE PROCESS IS GONE is still this session's, and is also
    one every other reader judges dead: a resumed session runs under a new
    process, and the claim names the old one. The answer then carries
    `"refresh": True` - the key is present only then - and `acquire` re-records
    the claim under the live process instead of answering "already yours" over
    it, so the lock goes on naming a run that holds it.

    The pid spelling matches only a caller that names no other session: a match
    on `$CLAUDE_PID` alone is the tie the docstring above gives to "ours", and a
    caller naming a different session is not a tie.
    """
    if not isinstance(info, dict) or not info:
        return {"ours": False, "why": "no lock to compare against"}
    sid, ident = _identity(session, pid)
    owner = info.get("sessionId")
    other_session = bool(sid) and bool(owner) and str(owner) != str(sid)
    token = info.get("token")
    # A CLAIM FOR ONE CALL is re-entered by nobody. Threads of one server share
    # a process, its pid and its environment, so neither answer below can tell
    # two of its requests apart - and the second request wrote beside the first.
    if info.get("perCall"):
        return {"ours": False,
                "why": "held for one call by pid %s - another call waits for it, "
                       "even from the same process" % (info.get("pid"),)}
    if token and not other_session and token in carried_tokens():
        return {"ours": True, "why": "this process carries the holder's token"}
    # A CLAIM A PROCESS TOOK FOR ITS OWN WRITE is that process's alone. Sharing
    # the session is what parallel tool calls of one run look like, so letting
    # the session back in here let each of them write over the others while
    # every one reported success; its children carry the token instead.
    if token and not info.get("handedOff"):
        if str(info.get("pid")) == str(os.getpid()) and not other_session:
            return {"ours": True, "why": "held by this process (pid %s)"
                                         % (os.getpid(),)}
        return {"ours": False,
                "why": "held for its own write by pid %s%s - another process of "
                       "one session is serialised, and only a child carrying the "
                       "holder's token is let back in"
                       % (info.get("pid"),
                          " (sessionId %s)" % (owner,) if owner else "")}
    # A claim taken BY HAND (`handedOff`), or one written before claims carried
    # a token: the session is the holder, which is the take-then-run-the-verbs
    # flow `reference/manifest-conventions.md` prescribes.
    if sid and info.get("sessionId") and str(info["sessionId"]) == str(sid):
        if holder_gone(info):
            return {"ours": True, "refresh": True,
                    "why": "held by this session (sessionId %s), under pid %s, "
                           "which is gone on this host" % (sid, info.get("pid"))}
        return {"ours": True,
                "why": "held by this session (sessionId %s)" % (sid,)}
    # THE PID RULE EXCLUDES A CALLER NAMING ANOTHER SESSION, as the token rule
    # does: subagents of one run share its $CLAUDE_PID, so a pid match alone let a
    # different session take a live holder's claim as its own.
    if (ident and info.get("pid") and str(info["pid"]) == str(ident)
            and not other_session):
        return {"ours": True, "why": "held by this session (pid %s)" % (ident,)}
    return {"ours": False,
            "why": "held by %s" % (info.get("sessionId") or info.get("pid")
                                   or info.get("hostname") or "someone else")}


def carried_tokens():
    """The tokens this process carries - its own takes and its parent's."""
    return set((os.environ.get(TOKEN_ENV) or "").split())


def _carry(token, keep):
    """Add `token` to this process's environment, or take it out of it.

    THE ENVIRONMENT IS THE CHANNEL ON PURPOSE: every subprocess a holder starts
    inherits it without the caller doing anything, and a process that did not
    descend from the holder cannot have it. The value names a claim, never a
    person or a machine, and nothing prints it.
    """
    have = [t for t in (os.environ.get(TOKEN_ENV) or "").split() if t != token]
    if keep:
        have.append(token)
    if have:
        os.environ[TOKEN_ENV] = " ".join(have)
    else:
        os.environ.pop(TOKEN_ENV, None)


def _identity(session, pid):
    """Every name THIS run goes by, for comparing against a claim.

    Not what gets written into one -- `_holder_pid` answers that, and the two
    questions came apart the moment the recorded pid had to be the holder's.
    Here the durable spellings are all wanted at once: a lock taken from Bash
    carries `$CLAUDE_CODE_SESSION_ID`, a hook is handed `session_id`, and
    `$CLAUDE_PID` is a third name for the same run, so a comparison that dropped
    one would refuse a run its own claim.
    """
    sid = session or os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    pid = pid or os.environ.get("CLAUDE_PID") or None
    try:
        pid = int(pid) if pid else None
    except (TypeError, ValueError):
        pid = None
    return sid, pid


def _holder_pid(pid, handed_off):
    """The pid to WRITE INTO a claim: the one whose death ends this hold.

    `judge` probes it, so recording a process that outlives the work answers a
    different question than the one asked. A caller that takes the lock and gives
    it back before it returns IS this process, and `os.getpid()` is then the
    identity whose death is the end of the hold -- while a durable session pid,
    alive long after the run it was handed to was killed, answers "still running"
    on behalf of work that stopped, and a claim recording no pid at all leaves the
    age rule holding a lock every run on this machine consults until the threshold
    runs out. Both of those are one killed run stalling every gate; they differ
    only in which door they came through.

    `handed_off` is the other shape, and it is why this default is not universal:
    a command that exits the instant it has taken the lock dies with its own pid,
    so recording that would make every lock taken from a shell read dead at once
    and let the next run seize what the operator is still holding. There the
    holder is the run that invoked the command, named by the caller or by the
    environment -- and with neither available no pid is recorded and the age rule
    applies, which is the answer that shape has always given.
    """
    given = pid or (os.environ.get("CLAUDE_PID") if handed_off else None)
    try:
        given = int(given) if given else None
    except (TypeError, ValueError):
        given = None
    if given is None and not handed_off:
        return os.getpid()
    return given


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


def _link_into_place(tmp, path, link, info):
    """Give the finished claim its real name, or write it where links cannot.

    Raises FileExistsError when that name is already claimed -- that IS the
    exclusivity test, so the caller's contention path runs exactly as it did
    when the create was the test.

    THE NAME BEING TAKEN IS A FACT ABOUT THE FILESYSTEM, NOT ABOUT AN
    EXCEPTION'S TYPE. `link()` reports a name already occupied as
    `FileExistsError` when the occupant is an ordinary file; a name occupied
    by a DIRECTORY reaches a permission refusal on at least one platform this
    project ships on instead -- the identical fact, worded two ways by two
    platforms. Asking the filesystem directly, once, is the check that reads
    the same on both: it is what makes the fallback below reachable only for
    an occupant NEITHER wording can be blamed on, rather than raising a
    platform-specific exception the caller has to have anticipated by name.

    The fallback exists because hard links are not universal, and a filesystem
    without them would otherwise leave a project with no lock rather than a
    weaker one. It reopens the window between the create and the write; what
    lands in that window is an empty claim, which `judge` reads for what it is.
    """
    try:
        link(tmp, path)
    except FileExistsError:
        raise
    except OSError:
        if os.path.exists(path):
            raise FileExistsError("already exists: %s" % (path,))
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)


def _claim(path, info, link=os.link):
    """Put a COMPLETE record at `path` -> `{"taken", "exists", "error"}`.

    Exactly one of the three is set. `taken`: this call created the claim.
    `exists`: somebody already has that name, and who they are is the caller's
    next question. `error`: the sentence naming what could not be done, which is
    a different fact from either of the other two and must be reported as one.

    THE RECORD LANDS WITH THE CLAIM OR THE FILE IS NOT THERE. A create followed
    by a write is two steps, and a run killed between them leaves a claim naming
    nobody on a lock every run on this machine consults. So the record goes into
    a sibling first and is linked into place, and the LINK is what refuses a name
    already taken -- the same no-window test the exclusive create was, with the
    write moved in front of it instead of behind.

    `link` IS AN ARGUMENT BECAUSE ITS FAILING BRANCH HAS TO BE REACHABLE. The
    fallback under it cannot be reached wherever hard links work, and no suite
    can take them away from the machine it is running on -- so the seam is how
    that branch gets driven at all, and a branch no case can drive is a branch
    nothing proves.
    """
    if os.path.exists(path):
        # ASKED BEFORE THE SIBLING IS BUILT, and not to save the work: a
        # directory can refuse a new file while still holding a live claim, and
        # a taker that reported "could not write" there would send its reader
        # after a permission problem instead of the run that holds the lock.
        return {"taken": False, "exists": True, "error": None}
    tmp = None                  # allocated inside the try, so the removal below
                                # can tell "never created" from "created"
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                                   prefix=".claim-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        # mkstemp is private to its creator; a lock the whole machine consults
        # has to be readable by whoever else is about to ask about it.
        os.chmod(tmp, 0o644)
        _link_into_place(tmp, path, link, info)
    except FileExistsError:
        return {"taken": False, "exists": True, "error": None}
    except OSError as exc:
        return {"taken": False, "exists": False, "error": "%s" % (exc,)}
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass            # a sibling left behind is litter, not a lock:
                                # `collect` reads `.lock` names and nothing else
    return {"taken": True, "exists": False, "error": None}


def _claim_stamp(path):
    """Enough of a claim file's identity to tell it from its replacement.

    Not the bytes, because the question is not what the claim says: it is whether
    the file judged a moment ago is still the file about to be removed, and an
    inode that was swapped answers that without a second read and a second parse.
    The mtime carries nanoseconds where the filesystem keeps them, and the size is
    there for the one that does not. None when there is nothing to stamp.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _take_over(path, info, stamp, record, link=os.link):
    """Replace the claim `stamp` names -> `_claim`'s answers, plus `displaced`.

    THE CREATE IS THE TEST HERE TOO, and that is the whole repair. Judging a claim
    and then writing over it is a read followed by a write, so two takers could
    pass one judgement and both write -- and the later one replaced a claim that
    was by then live, which is the state the lock exists to prevent, reached
    through the door built for recovery. So the judged claim is removed only while
    it is still the file that was judged, the name is then taken with the same
    exclusive create a free lock is taken with, and whoever loses that create is
    told it lost instead of overwriting the winner.

    `record` is merged in ONLY where this call removed the claim it judged. A
    holder that let go by itself was displaced by nobody, and a row saying
    otherwise carries a basis for an event no one observed -- which is worse than
    carrying none, because it outlives every reader who could have contradicted it.
    """
    displaced = False
    if stamp is not None and _claim_stamp(path) == stamp:
        try:
            os.unlink(path)
            displaced = True
        except FileNotFoundError:
            pass                # the holder let go in that instant: the name is
                                # free and nothing was taken from anybody
        except OSError as exc:
            return {"taken": False, "exists": False, "error": "%s" % (exc,),
                    "displaced": False}
    if displaced:
        info = dict(info)
        info.update(record)
    res = _claim(path, info, link=link)
    res["displaced"] = bool(displaced and res["taken"])
    return res


def _displaced_record(info):
    """The identity a takeover row may name, or {} when the claim named nobody."""
    return {k: info.get(k) for k in
            ("sessionId", "hostname", "pid", "startedAt", "note")
            if info.get(k) is not None}


def _unattributed_claim(info, path):
    """What was replaced, for a claim that named nobody -- as a sentence.

    THE ROW MAY NOT CALL THESE ONE THING. A claim with nothing in it is a take
    that never recorded itself; a claim carrying bytes that will not parse is
    something a writer wrote, which is why one reads dead here and the other stays
    live. An empty mapping under a key meaning "the run this was taken from" says
    neither, and reads to a later reader as a run to go looking for.
    """
    if _interrupted_take(info, path):
        return "a take that did not finish recording itself"
    return "a claim that could not be read, so its holder was never named"


# --- taking and giving back ----------------------------------------------------
# `acquire` and `release` take plain arguments rather than an argparse Namespace,
# and that is the whole reason they could move. They were `cmd_acquire(args, out)`
# and `cmd_release(args, out)` in `audit-lock.py`, which meant the only way for
# another module to TAKE a lock was to build an argv and call that command's
# `main()` through the panel's read-side accessor. `_deps` could not see that
# edge (the literal sat in `_panel_state`, so the graph blamed the panel) and it
# was real all the same: a hidden dependency is not a retired one.
#
# AND IT WAS WORSE THAN HIDDEN ON ONE SIDE. That accessor answers with THIS
# module, which has no `main` and never did, so the panel's own write path asked
# for an entry point that does not exist here and fell into a bare handler on
# every save -- a wrong module reaching a caller wearing contention's clothes,
# while the working-tree fallback underneath it went on guarding a clone the
# command line was not using.
#
# SO THE RULE IS NOW A PROPERTY OF THE CALL AND NOT OF THE CALLER'S CARE. Both
# are functions here, `audit-lock.py` wraps them for the CLI, and every caller
# that needs to acquire says so in an import the layer lint can read. A missing
# attribute cannot be reached that way, and a caller that still wraps the call
# owes its handler the distinction the fallback used to swallow: a lock that
# refused and a call that could not be made are different answers, and only one
# of them is about another run.
def held(code):
    """True when an `acquire` return value means the lock IS held.

    `acquire` returns an INT on every path - 0 held, `E_ERR` / `E_USAGE` /
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

    `E_OURS` IS HELD AND IS NOT `0`. A caller that already had the lock may
    proceed exactly as one that has just taken it; what it may not do is give the
    lock back, and `took()` is the question that separates those. A caller that
    released on this answer would drop the claim out from under the hold that was
    still using it -- the failure the panel's borrowed handle exists to avoid.
    """
    return code in (0, E_OURS)


def took(code):
    """True when THIS call created the claim -- the caller that must release it.

    Published beside `held()` for `held()`'s own reason, one question later. The
    two were one question while there was a single way to hold a lock, and an
    answer for re-entry made them two: proceeding and releasing stopped having
    the same precondition, and a call site left deciding that for itself is
    exactly what put a lock on disk after every write the last time.
    """
    return code == 0


def available(project):
    """True when this project has a lock scheme at all.

    THE THIRD ANSWER, and leaving it out re-broke the panel. `acquire` returns
    `E_ERR` both for "not a git repository" - where there is no lock to take and
    never was - and for a directory or a claim it could not write. A caller that
    refuses to write on every non-zero code therefore refuses in a project with no
    `.git`, which is a case the panel has a documented fallback for: it drops to a
    working-tree lockfile and proceeds under the weaker guarantee.

    So the question is asked BEFORE acquiring, where it has an unambiguous answer,
    rather than inferred afterwards from a code that means two things. Found by the
    browser gate: `held()`'s int-vs-dict repair, correct for a contended lock,
    made every proposal write in a non-git fixture refuse.
    """
    return bool(lock_dir(project))


def refusal(code, name):
    """One line for a caller that could not take `name`, safe to put in a payload.

    THE TERMINAL LINES ARE NOT THIS. `acquire` writes a verdict plus indented
    detail through `out`, and that detail names the HOST the live pid runs on and,
    on two paths, an absolute project directory. Those lines are for a terminal
    the operator is already sitting at. A caller that hands them to a structured
    `findings` list publishes them: the panel paints proposal findings, so the
    first draft of `held()`'s int-vs-dict repair moved a hostname onto an HTTP
    response - the
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


def release_refusal(code, name):
    """One line for a caller whose RELEASE was declined, safe to put in a payload.

    A DECLINED RELEASE IS THE ONLY NEWS OF A TAKEOVER THE LOSER EVER GETS. The
    lock refuses to let a run give back what is no longer its own, and callers
    silenced that refusal into a no-op printer and then dropped the code -- so a
    session that had been displaced finished its work, cleaned up, and reported
    success, while the sentence saying another run had been writing beside it
    went nowhere. The repair is that the refusal is a value somebody reads.

    `refusal`'s rule about hosts and absolute paths holds here for the same
    reason: this sentence is built for a structured payload, and the terminal
    lines stay where they were already going.
    """
    if code == E_LIVE:
        return ("the %s lock was NOT released -- it is no longer this run's, so "
                "another session took it over while this work was running. "
                "Re-read anything written since before trusting it; "
                "`audit-lock.py status` says who holds it now" % (name,))
    if code == E_USAGE:
        return "the %s lock was asked for by a name it does not have" % (name,)
    return ("the %s lock could not be released (exit %s) -- run `audit-lock.py "
            "status` for the reason" % (name, code))


def _replace_own(path, info, stamp, record, name, out):
    """Write `info` over this session's own claim `stamp` names -> None when it
    landed, else the exit code, with the line saying why already printed.

    Through `_take_over`, so the replacement is decided by the same exclusive
    create a takeover is: a claim that changed hands since it was read is not
    written over, and the caller is told it lost."""
    try:
        res = _take_over(path, info, stamp, record)
    except Exception as exc:
        out("[audit-lock] could not rewrite %s: %s" % (name, exc))
        return E_ERR
    if res["error"]:
        out("[audit-lock] could not rewrite %s: %s" % (name, res["error"]))
        return E_ERR
    if not res["taken"]:
        out("[audit-lock] %s went to another run while it was being rewritten "
            "-- it is NOT yours" % (name,))
        out("             `audit-lock.py status` says who holds it now.")
        return E_LIVE
    return None


def _rerecord(path, current, stamp, live_pid, name, out, taken=False):
    """Re-record this session's hand-off claim under `live_pid` -> `E_OURS`, `0`
    when `taken`, or the code `_replace_own` refused with.

    THE HOLD IS THE SAME HOLD: its note, session, token and any takeover record
    are kept, so whatever releases it by note or by session still finds it. Only
    the process it names changes, to one that is running, and `refreshedFrom`
    keeps the pid it replaced.

    `taken` IS A HAND-OFF ACQUIRE OVER A HOLD WHOSE PROCESS IS GONE. Nothing that
    took that hold is still running to give it back, so the run asking - a
    resumed session under a new process - is the one that must: the answer is
    `0`, the claim's token is carried, and the line says the hold is this call's.
    Answered `E_OURS` there, the resumed run left the lock on disk at its end,
    naming a process with no release coming. Every other caller gets `E_OURS`:
    the claim is still the hold's to give back, not this call's.
    """
    info = dict(current)
    info.update({"pid": live_pid, "hostname": platform.node(),
                 "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "refreshedFrom": current.get("pid")})
    code = _replace_own(path, info, stamp, {}, name, out)
    if code is not None:
        return code
    if taken:
        if current.get("token") and not current.get("perCall"):
            _carry(current["token"], True)
        out("[audit-lock] acquired %s -- this session's own claim, re-recorded "
            "under pid %s, the run asking, from pid %s, which is gone"
            % (name, live_pid, current.get("pid")))
        out("             Nothing that took it is running to give it back, so "
            "the hold is this call's now: release it at the end of the run.")
        return 0
    out("[audit-lock] %s is this session's -- re-recorded under pid %s, the "
        "run asking, in place of pid %s" % (name, live_pid, current.get("pid")))
    out("             The hold is otherwise unchanged and still not this call's "
        "to give back.")
    return E_OURS


def refresh(project, name, session=None, pid=None, out=print):
    """Make this session's hand-off claim on `name` name the run asking -> code.

    `E_OURS` when the claim is this run's: re-recorded under `pid` (or
    `$CLAUDE_PID`), already naming it, with no pid to name, naming a process that
    is not gone, or not a hand-off claim - whose pid is the process that took
    it, not a run to re-name - each said in its line. `E_LIVE` when the claim is
    not this run's at all; `E_ERR`/`E_USAGE` as `acquire` answers them.

    ONLY A HOLDER THAT IS GONE, OR NONE RECORDED, IS RE-RECORDED. A live recorded
    pid is the process whose release gives the hold back, and `release` compares
    the pid it records: moving the claim onto a second live process of the same
    session made that release read as a takeover and refused it.

    For a caller that already holds the lock through `acquire`'s re-entry answer
    and must not leave it naming a process other than the one running the work:
    a resumed session, or the same session under a second process.
    """
    ld = lock_dir(project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % project)
        return E_ERR
    if not valid_name(name):
        out(name_refusal(name))
        return E_USAGE
    path = os.path.join(ld, name + ".lock")
    current = read_lock(path)
    mine = held_by_us(current, session=session, pid=pid)
    if not mine["ours"]:
        out("[audit-lock] %s is not this run's (%s) -- nothing re-recorded"
            % (name, mine["why"]))
        return E_LIVE
    if not current.get("handedOff"):
        out("[audit-lock] %s is this run's and not a hand-off claim, so the pid "
            "it records is the process that took it -- left as it is" % (name,))
        return E_OURS
    if current.get("pid") and not holder_gone(current, path):
        _live, basis = judge(current, path)
        out("[audit-lock] %s is this session's and its recorded holder is not "
            "gone (%s) -- left as it is" % (name, basis))
        return E_OURS
    live_pid = _holder_pid(pid, True)
    if not live_pid:
        out("[audit-lock] %s is this session's; no pid names the run asking, so "
            "it keeps pid %s" % (name, current.get("pid")))
        return E_OURS
    if str(current.get("pid")) == str(live_pid):
        out("[audit-lock] %s is this session's and already names pid %s"
            % (name, live_pid))
        return E_OURS
    return _rerecord(path, current, _claim_stamp(path), live_pid, name, out)


def taken_from(info, session=None):
    """True when the claim `info` records taking over from THIS session.

    The one fact that tells a run whose lock was taken from it apart from a run
    that never held the lock: both meet a claim naming somebody else, and only
    the first was displaced. A session on both sides, or the answer is None
    compared with None.
    """
    sid, _pid = _identity(session, None)
    if not sid or not isinstance(info, dict):
        return False
    return (info.get("takenOverFrom") or {}).get("sessionId") == sid


def acquire(project, name, note=None, takeover=False, session=None, pid=None,
            out=print, wait=None, handed_off=False, per_call=False, yields=False):
    """Take `name` for this project -> an exit code, which `held()` reads.

    `wait` is how long a LIVE holder is waited out before the refusal is printed,
    defaulting to `WAIT_SECONDS`; zero refuses the moment the name exists. Three
    answers are never waited for, because waiting cannot change any of them: a
    holder that is not alive will not become any more gone, a claim this run
    already holds is this run's, and a claim that could not be written names a
    directory rather than a holder.

    `handed_off` says the lock outlives this process -- a command that exits with
    it still held. `_holder_pid` is where that changes what the claim records,
    and why the default is the other way round.

    `per_call` says the claim belongs to one CALL rather than to this process -
    a server serving requests on threads - so its token is not carried and no
    other call re-enters it (`held_by_us`).

    `yields` marks a claim its OWN session's later hand-off acquire takes over:
    a hold taken for a verb's bookkeeping that a longer hold of the same session
    supersedes, re-taken under that hold's note and no longer yielding, so the
    verb that releases the yielding claim by its note leaves the longer hold in
    place. Another session's acquire meets it as any live claim.

    A claim this session holds whose pid is gone (`held_by_us`'s `refresh`) is
    re-recorded under the run asking (`_rerecord`) rather than answered as
    already held; with no pid to record it is judged like any other claim. A
    `handed_off` acquire that re-records it holds it from then on and answers
    `0` - the resumed run that asked is the one to give it back; any other
    caller is answered `E_OURS`.

    Superseding a yielding claim needs the caller to NAME the claim's session:
    a caller with no session id and the holder's `$CLAUDE_PID` is "ours" to
    `held_by_us`'s tie, and that tie is for answering re-entry, not for taking
    a claim over.
    """
    ld = lock_dir(project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % project)
        return E_ERR
    if not valid_name(name):
        out(name_refusal(name))
        return E_USAGE
    try:
        os.makedirs(ld, exist_ok=True)
    except OSError as exc:
        out("[audit-lock] cannot create %s: %s" % (ld, exc))
        return E_ERR
    variant = case_variant(ld, name)
    if variant:
        out("[audit-lock] %s is refused: a lock named %s already exists -- the two differ "
            "only in case, and a case-folding filesystem stores them as one file"
            % (name, variant))
        out("             Refused on every platform, so two runs cannot hold one "
            "claim on Linux that they would share on macOS or Windows.")
        return E_LIVE

    sid, _own = _identity(session, pid)
    holder = _holder_pid(pid, handed_off)
    # `token` is what re-entry is decided by for a claim a process takes for its
    # own write; `handedOff` marks the claim a command exits holding, which its
    # session goes on working under (`held_by_us`).
    info = {"hostname": platform.node(), "note": note or name,
            "token": os.urandom(12).hex(), "handedOff": bool(handed_off)}
    if per_call:
        info["perCall"] = True
    if yields:
        info["yields"] = True
    if holder:
        info["pid"] = holder
    if sid:
        info["sessionId"] = sid

    path = os.path.join(ld, name + ".lock")
    deadline = time.monotonic() + (WAIT_SECONDS if wait is None else float(wait))
    while True:
        # STAMPED EACH TIME ROUND, so the claim dates from when it landed rather
        # than from when the first attempt was refused. The age rule reads this
        # field, and a wait that pre-aged its own claim would shorten the
        # threshold by however long the caller spent waiting.
        info["startedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        claim = _claim(path, info)
        if claim["taken"]:
            if not per_call:
                _carry(info["token"], True)
            out("[audit-lock] acquired %s%s" % (name, "" if holder else
                                                " (no pid recorded -- age rule applies)"))
            return 0
        if claim["error"]:
            # FAIL OPEN, AND SAY WHICH QUESTION WENT UNANSWERED. This lock is a
            # coordination advisory rather than a guard, and an advisory that
            # cannot be written must not stop the work it was advising about --
            # nor reach its caller as an exception, which costs a run rather than
            # a lock. What it must never do is borrow the sentence for a lock
            # that is HELD: nobody was found and nobody was probed, so an
            # operator sent to wait for a live run would be waiting for a run
            # that was never there.
            out("[audit-lock] could not take %s: %s" % (name, claim["error"]))
            out("             NOT a report that %s is held -- the claim could not be "
                "written, so nothing was established about who, if anyone, has it."
                % (name,))
            out("             The lock is advisory: this refuses the LOCK, not the "
                "work. Fall back to whatever guard you have, or fix %s." % (ld,))
            return E_ERR

        current = read_lock(path)
        mine = held_by_us(current, session=session, pid=pid)
        if mine["ours"] and not is_user_name(name):
            stamp = _claim_stamp(path)
            same_session = (bool(sid) and str(current.get("sessionId") or "")
                            == str(sid))
            if (handed_off and current.get("yields") and not yields
                    and same_session):
                code = _replace_own(path, info, stamp,
                                    {"supersededNote": current.get("note")},
                                    name, out)
                if code is not None:
                    return code
                if not per_call:
                    _carry(info["token"], True)
                out("[audit-lock] acquired %s from this session's own yielding "
                    "claim (%s) -- the hold is this call's now"
                    % (name, current.get("note") or name))
                return 0
            live_pid = _holder_pid(pid, True) if mine.get("refresh") else None
            if live_pid:
                return _rerecord(path, current, stamp, live_pid, name, out,
                                 taken=handed_off)
            if not mine.get("refresh"):
                # RE-ENTRY IS ANSWERED BEFORE ANYTHING IS WAITED FOR. A command
                # that holds this lock and calls another command that takes it
                # would otherwise spend the whole bound waiting for itself and
                # then be refused by its own claim.
                out("[audit-lock] %s is already yours (%s) -- nothing was taken"
                    % (name, mine["why"]))
                out("             Whatever took it still needs it, so this is "
                    "not yours to give back: proceed, and leave the release to "
                    "the hold that owns it.")
                return E_OURS
            # A claim of this session naming a gone process, with no live pid
            # to re-record it under: judged below like any other claim, which
            # reads it dead.
        stamp = _claim_stamp(path)
        live, basis = judge(current, path)
        if takeover or not live or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)

    who = _claim_holder(current, path)
    what = current.get("note") or name
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

    # THE ROW SAYS WHAT WAS THERE AND NOT WHAT A KEY IMPLIES. A claim that named
    # somebody is named; one that named nobody is described instead, because an
    # empty mapping under `takenOverFrom` reads as a run to go and find and says
    # the same thing for a take that never finished and for bytes nothing could
    # parse -- a distinction this module keeps apart everywhere else.
    record = {"takenOverBasis": basis}
    seized = _displaced_record(current)
    if seized:
        record["takenOverFrom"] = seized
    else:
        record["takenOverFound"] = _unattributed_claim(current, path)
    try:
        res = _take_over(path, info, stamp, record)
    except Exception as exc:
        out("[audit-lock] takeover failed: %s" % exc)
        return E_ERR
    if res["error"]:
        out("[audit-lock] takeover failed: %s" % res["error"])
        return E_ERR
    if not res["taken"]:
        out("[audit-lock] %s went to another run while this takeover was being "
            "decided -- it is NOT yours" % (name,))
        out("             Nothing here was replaced. `audit-lock.py status` "
            "says who holds it now.")
        return E_LIVE
    if not per_call:
        _carry(info["token"], True)
    if not res["displaced"]:
        out("[audit-lock] acquired %s -- the claim this was to take over from "
            "was already gone, so nothing was displaced" % (name,))
        return 0
    out("[audit-lock] took over %s from %s" % (name, who))
    out("             basis: %s" % basis)
    if live:
        out("             WARNING: that run looked LIVE. Both sessions may now write.")
    return 0


def _release_conflict(held, session, pid):
    """`{"mismatch", "who"}` -- does the WHOLE identity a claim recorded rule
    this caller out from releasing it?

    A take records a session id AND a pid; comparing the session alone left
    the pid recorded and never read, so two processes sharing one session --
    each a real taker with its own pid -- could not be told apart, and the
    second one's release succeeded against a claim the first still holds.
    Both fields are compared now, and a mismatch on EITHER is enough to
    refuse: an unrecorded field proves nothing, the same rule the age
    fallback already applies when no identity was written at all, so only a
    field that IS recorded on the claim and DOES differ counts.

    THE CANDIDATE SET HAS TWO MEMBERS, NOT ONE, and that is what keeps an
    ordinary same-process round trip from refusing itself. A caller that took
    the lock and means to give it back before it returns recorded
    `os.getpid()` at acquire time (`_holder_pid`'s reason); a caller that took
    it through a command that then exited recorded `$CLAUDE_PID` instead.
    Release cannot know which shape produced the claim it is reading, so both
    of this call's own spellings are offered and either is accepted -- which
    is what stops the ordinary in-process pattern (acquire, then release,
    with no pid ever handed to either call) from reading `$CLAUDE_PID` as a
    stranger's pid and refusing a caller its own claim.
    """
    if not isinstance(held, dict) or not held:
        return {"mismatch": False, "who": "someone else"}
    # A HOLDER THAT IS DEAD ON THIS HOST is displaced by nobody: its run is gone,
    # so releasing its claim takes the lock from no one. Refusing it made the
    # recovery line the panel prints for a crashed panel a command that always
    # failed. A holder on another host, or one with no pid, is not known dead and
    # keeps the identity rule below.
    if holder_gone(held):
        return {"mismatch": False, "who": "a run that is gone"}
    sid, ident = _identity(session, pid)
    owner = held.get("sessionId")
    session_mismatch = bool(owner) and bool(sid) and str(owner) != str(sid)
    candidates = set(str(c) for c in (os.getpid(), ident) if c is not None)
    holder_pid = held.get("pid")
    pid_mismatch = (holder_pid is not None
                    and str(holder_pid) not in candidates)
    if session_mismatch:
        who = owner
    elif pid_mismatch:
        who = "pid %s" % (holder_pid,)
    else:
        who = owner or holder_pid or held.get("hostname") or "someone else"
    return {"mismatch": session_mismatch or pid_mismatch, "who": who}


def release(project, name, session=None, pid=None, force=False, out=print):
    ld = lock_dir(project)
    if not ld:
        out("[audit-lock] not a git repository: %s" % project)
        return E_ERR
    if not valid_name(name):
        out(name_refusal(name))
        return E_USAGE
    # REFUSED ONLY WHERE THE UNLINK WOULD HIT THE OTHER SPELLING: the exact name
    # is not in the directory, a variant is, so the filesystem folds case and
    # `path` IS that variant's file. With the exact name listed the two are two
    # files, and this one - `--force` included - is released like any other.
    variant = case_variant(ld, name)
    if variant and not _listed(ld, name):
        out("[audit-lock] %s differs only in case from the lock %s, which this "
            "case-folding filesystem stores as the same file -- refused so that "
            "releasing one spelling cannot remove the other" % (name, variant))
        return E_USAGE
    path = os.path.join(ld, name + ".lock")
    if not os.path.exists(path):
        out("[audit-lock] %s was not held -- nothing to release" % name)
        return 0
    held = read_lock(path)
    conflict = _release_conflict(held, session, pid)
    # Releasing a lock that is no longer yours is how a session that was taken
    # over finds out -- today it deletes the winner's lock and neither ever knows.
    if conflict["mismatch"] and not force:
        out("[audit-lock] %s is NOT yours to release -- held by %s"
            % (name, conflict["who"]))
        out("             You were taken over. Anything you wrote since may have")
        out("             raced that session. Re-read the shard before trusting it.")
        if taken_from(held, session):
            out("             (this lock records taking over from you)")
        return E_LIVE
    try:
        os.unlink(path)
    except OSError as exc:
        out("[audit-lock] cannot remove %s: %s" % (path, exc))
        return E_ERR
    if held.get("token"):
        _carry(held["token"], False)
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_locks.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__locks.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
