#!/usr/bin/env python3
"""
One child process tree run so that it can be stopped WHOLE, and a stop signal
turned into an exception so a caller's `finally` runs.

WHY A MODULE. `run-test-gate.py` solved both halves first: a timed-out
`subprocess.run` kills only the direct child, so a runner's grandchildren went on
running and writing; and SIGTERM, with no handler, ends the interpreter without
running a `finally`, so whatever the caller had built was left behind.
`stamp-verification.py red` met the same two failures - a throwaway tree left
registered in git after a SIGTERM, and a grandchild writing into a directory
being removed - so the answer moved here, where both entry points share it,
instead of being written a second time.

AND THE SHELL A PLAN COMMAND RUNS UNDER. `run-test-gate.py` spawned through
`shell=True` - `cmd.exe` on Windows - while `derive-phase-gate.py` named
`/bin/sh`, which Windows does not have; neither ran a plan's POSIX spellings
there. `shell_argv` is the one answer both now take.

WHAT IT CANNOT COVER: SIGKILL. It cannot be caught, so no handler runs and no
`finally` runs; a caller that must account for what it built says so, and reports
a leftover by name the next time it runs.
"""
import os
import shutil
import signal
import subprocess
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

# How long a torn-down group is given to die politely before SIGKILL. Small on
# purpose: this runs after a child has already overrun its whole budget.
GRACE_SECONDS = 5


# --- one child tree, stopped whole ----------------------------------------------
def group_kwargs():
    """Popen kwargs that put the child in a group we can tear down whole.

    POSIX gets `start_new_session` (setsid), so the child becomes a process-group
    LEADER and `killpg` reaches everything it started. Windows gets its own
    process group for the same purpose. A platform offering neither is left alone
    rather than guessed at - `tear_down` then reports that it could not confirm.

    THE TRADE IS DELIBERATE AND IS WHY `arm_interrupt` EXISTS. Detaching from the
    controlling terminal means a Ctrl-C no longer reaches the children BY
    ACCIDENT; that is given up to gain a teardown that is the same on all three
    paths - timeout, SIGINT and SIGTERM - instead of one that happens to work on
    one of them. Only the grouping lives here: which shell a plan command runs
    under is `shell_argv`'s, and where the output goes is the caller's.
    """
    if hasattr(os, "setsid"):
        return {"start_new_session": True}
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


def shares_our_group(pid):
    """Whether `pid` sits in THIS process's group - i.e. whether signalling that
    group would signal us.

    A NAMED PREDICATE RATHER THAN AN INLINE COMPARISON, because the branch it
    guards cannot be covered by observing the alternative: a case that removed
    the guard and called `tear_down` would signal its own runner and die, which
    reads as infrastructure trouble rather than as a caught defect. The decision
    is testable here, and `tear_down`'s use of it is reached by swapping this
    name - the same seam `test__journal_io` uses on `_git_anchor_finding`.

    True on any error, which is the safe direction: unable to tell whether we
    would hit ourselves means do not aim at the group.
    """
    try:
        return os.getpgid(pid) == os.getpgid(0)
    except Exception:
        return True


def tear_down(proc):
    """Kill the process GROUP. True when that could be confirmed, False when not.

    THE FAULT THIS EXISTS FOR: `subprocess.run(timeout=)` kills the DIRECT child,
    and under `shell=True` the direct child is the shell. `npx` -> `node` -> its
    workers outlive it, keep running, and keep WRITING - into the tree the gate is
    about to describe, or the throwaway `red` is about to remove. A survivor does
    not merely leak a process; it turns whatever the caller does next into a race.

    SIGTERM, a grace period, then SIGKILL, because a test runner asked to stop
    politely usually flushes its output and a runner that ignores that is not
    going to be reasoned with. The return value is what the caller records: a
    teardown that could not be confirmed is a fact about the run, and reporting it
    as a clean stop would be a claim with nothing behind it.
    """
    try:
        if hasattr(os, "killpg"):
            gid = os.getpgid(proc.pid)
            if shares_our_group(proc.pid):
                # THE CHILD IS IN OUR OWN GROUP, so `killpg` here would signal
                # THIS process - the caller - and not the child's tree. That is
                # not hypothetical: with `start_new_session` removed the whole
                # test runner died mid-suite, which is how this branch was found.
                # A platform with no `setsid` reaches the same state honestly, so
                # the narrow kill is taken and the answer is `False`: the direct
                # child goes, its descendants are not accounted for, and the caller
                # says the teardown could not be confirmed rather than implying a
                # clean stop.
                proc.kill()
                try:
                    proc.wait(timeout=GRACE_SECONDS)
                except Exception:
                    pass
                return False
            os.killpg(gid, signal.SIGTERM)
            try:
                proc.wait(timeout=GRACE_SECONDS)
            except Exception:
                os.killpg(gid, signal.SIGKILL)
                proc.wait(timeout=GRACE_SECONDS)
            return True
        completed = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return completed.returncode == 0
    except Exception:
        return False


def drain(proc):
    """Whatever the child had already written, after the group is gone.

    Called AFTER the kill and never instead of it: a timed-out child is often
    blocked on a full pipe, so reading first would wait on a process nothing is
    going to stop. Failure here costs a diagnostic, never the teardown."""
    try:
        out, _err = proc.communicate(timeout=GRACE_SECONDS)
        return (out or b"").decode("utf-8", "replace")
    except Exception:
        return ""


# --- one POSIX shell, on every platform ---------------------------------------
# A plan's commands are written in POSIX shell - `export`, single quotes,
# `${VAR}`, `&&` chains a `meta.nodePreamble` builds - so they are run by ONE
# POSIX `sh` wherever this runs. `shell=True` is not that: on Windows it is
# `cmd.exe`, which reads none of those spellings, and a command it misreads
# still exits with a code that looks like an answer.
POSIX_SH = "/bin/sh"

NO_POSIX_SH = (
    "no POSIX shell was found to run this plan's commands: %s is absent, no "
    "`sh` is on PATH, and none sits beside `git`. The plan's commands are POSIX "
    "shell, so they are NOT handed to cmd.exe instead. On Windows, install Git "
    "for Windows (https://gitforwindows.org) and run from Git Bash, or put its "
    "`usr\\bin` directory on PATH." % (POSIX_SH,))

# Where Git for Windows keeps its `sh.exe`, relative to its install root. The
# default installer puts only `<root>\cmd` on PATH, so a `git` that resolves
# while `sh` does not is the ordinary Windows state, not an exotic one.
_GIT_SH_RELS = (("usr", "bin", "sh.exe"), ("bin", "sh.exe"))


def _in_system_dir(path, environ):
    """Whether `path` sits under Windows' own system directory.

    `System32\\bash.exe` is the WSL launcher: it runs the command inside a Linux
    VM with its own filesystem view, so the plan's paths would not name the
    files the gate is judging. Nothing found there is taken as the shell -
    which is why there is no bare `bash` fallback at all: every Git or MSYS
    directory that holds a `bash` holds an `sh` beside it, so the one `bash` a
    fallback could add is exactly this one.
    """
    root = (environ.get("SystemRoot") or environ.get("SYSTEMROOT")
            or environ.get("windir") or "")
    if not root or not path:
        return False
    base = os.path.normcase(os.path.normpath(root))
    here = os.path.normcase(os.path.normpath(path))
    return here == base or here.startswith(base.rstrip("\\/") + os.sep)


def resolve_sh(isfile=None, which=None, environ=None):
    """`(path, None)` for the POSIX shell a plan command runs under, or
    `(None, sentence)` saying none exists and what to install.

    `/bin/sh` FIRST, and when it is there nothing else is asked - that is the
    exact interpreter `subprocess`'s `shell=True` uses on POSIX, so a POSIX
    machine runs every command byte for byte as before. Then the `sh` on PATH,
    which is Git for Windows' under Git Bash; then the one beside `git`, for the
    default Windows install that puts only `git` on PATH.

    NEVER A FALLBACK TO `cmd.exe`, and never a bare `"sh"` handed to the OS to
    find: the first reads the plan's commands in another language, and the
    second fails at spawn time with an error that names no remedy. The refusal
    is the answer, and the callers turn it into could-not-run.

    The three arguments are seams for the cases; production passes none.
    """
    isfile = isfile if isfile is not None else os.path.isfile
    which = which if which is not None else shutil.which
    environ = environ if environ is not None else os.environ
    if isfile(POSIX_SH):
        return POSIX_SH, None
    found = which("sh")
    if found and not _in_system_dir(found, environ):
        return found, None
    git = which("git")
    if git and not _in_system_dir(git, environ):
        here = os.path.dirname(os.path.normpath(git))
        for root in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
            for rel in _GIT_SH_RELS:
                candidate = os.path.join(root, *rel)
                if isfile(candidate):
                    return candidate, None
    return None, NO_POSIX_SH


def shell_argv(command):
    """`(argv, None)` running `command` under the resolved POSIX shell, or
    `(None, sentence)` when there is none.

    `resolve_sh` is looked up at CALL time, not bound as a default, so a case
    can swap it for one that finds nothing and drive a caller's refusal path -
    the same seam `shares_our_group` gives `tear_down`.
    """
    sh, refusal = resolve_sh()
    if sh is None:
        return None, refusal
    return [sh, "-c", command], None


# --- stopping this process ----------------------------------------------------
# A TERMINAL'S Ctrl-C DOES NOT REACH THE CHILDREN, by construction rather than by
# accident: `group_kwargs` puts every child in a session of its own, so the signal
# arrives HERE and nowhere else. That trade is stated there - one teardown that is
# the same on all three paths instead of one that happens to work on one of them -
# and these two functions are the half of it that was never written. SIGTERM has
# no default that could stand in either: with no handler the interpreter simply
# dies, the detached group outlives it, and the run leaves neither a record nor a
# stopped child.
INTERRUPT_SIGNALS = ("SIGINT", "SIGTERM")


def raiser(word):
    """A handler that raises the interrupt NAMING the signal it was installed for.

    The name is bound at install time because that is the only place it is known
    without a second table to keep in step - and a `cancelled` row owes its reader
    the thing that stopped the run, which is the whole of that row's basis.

    `KeyboardInterrupt` rather than an exception of this file's own: SIGINT already
    raises it, so ONE arm in a caller covers both signals instead of two that can
    drift apart. It is a `BaseException`, which is what carries it past every
    `except Exception` between here and there.
    """
    def _handler(_signum, _frame):
        raise KeyboardInterrupt(word)
    return _handler


def arm_interrupt():
    """Install the handlers; return what they displaced, for `disarm_interrupt`.

    NOT GUARDED AGAINST `ValueError`. `signal.signal` refuses off the main thread,
    and this file is an entry point - a caller that reaches that state has a
    defect, and swallowing it would hide the one fact that matters here, which is
    that the interrupt path is NOT armed.
    """
    previous = []
    for name in INTERRUPT_SIGNALS:
        sig = getattr(signal, name)
        previous.append((sig, signal.signal(sig, raiser(name))))
    return previous


def disarm_interrupt(previous):
    """Put back exactly what `arm_interrupt` displaced.

    A handler left installed outlives the call, and `main` is a function the
    suites drive many times in one process - so this is a `finally`, not a
    courtesy.

    `None` is what `signal.signal` returns for a handler that was not set from
    Python, and it cannot be handed back: `signal.signal(sig, None)` is a
    TypeError. The default is restored in that case, which is the honest reading -
    there is no Python handler to return to.
    """
    for sig, handler in previous:
        signal.signal(sig, signal.SIG_DFL if handler is None else handler)


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_proc_group.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__proc_group.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
