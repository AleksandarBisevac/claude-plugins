#!/usr/bin/env python3
"""
The cases for `_locks.py` — the lock library, and the boundary that made it one.

`audit-lock.py`'s own cases live in `test_audit_lock.py` and run over these
same functions through that command's aliases; they are not repeated here. What
this file asserts is the thing that suite structurally cannot: that there is ONE
implementation, that `audit-lock.py` re-exports it rather than keeping a copy,
and that the module is reachable and self-sufficient at layer 1 — which is the
whole reason four callers could stop loading a command to ask about a lock.

WHY THAT IS WORTH ITS OWN FILE. A split leaves two ways to be wrong and only one
of them shows up in behaviour. The first — the extraction broke something — is
what the cases next door catch, and they caught a real one (`audit-task`'s
acquire path). The second is silent: someone pastes a helper back into
`audit-lock.py`, both files work, both suites stay green, and the two drift for
months. Only an identity assertion fails on that, and only if something makes it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _locks as M                                 # noqa: E402

_CMD = _loader.load_script("audit-lock.py", modname="audit_lock_boundary")


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the boundary ---------------------------------------------------------
    # Every name `audit-lock.py` spells must BE this module's object. A copy
    # pasted back there passes every behavioural case in both suites and fails
    # only here.
    _shared = ("STALE_MINUTES", "pid_alive", "_age_minutes", "judge", "lock_dir",
               "valid_name", "read_lock", "collect", "acquire", "release",
               "_identity", "_write_lock")
    _forked = sorted(n for n in _shared
                     if getattr(_CMD, n, None) is not getattr(M, n))
    check("b1 audit-lock.py re-exports all %d shared names as THIS module's own "
          "objects - not one is a second implementation: %r"
          % (len(_shared), _forked),
          _forked == [])
    # The second direction, and it reads vacuous next to b1 on purpose: b1 also
    # passes if a name is simply missing from `audit-lock.py`, because
    # `getattr(..., None) is getattr(M, n)` would then compare None to a function
    # and... would fail. So this is not that. What b2 catches is the opposite
    # mutation: `_shared` shrinking. A future edit that stops re-exporting
    # `judge` would make b1 vacuously true over a shorter list unless the list is
    # itself checked against what the command actually carries.
    _missing = sorted(n for n in _shared if not hasattr(_CMD, n))
    check("b2 ...and every one of them is actually PRESENT on audit-lock.py, so "
          "b1 cannot pass over a list that quietly got shorter: %r" % (_missing,),
          _missing == [])
    check("b3 the exit codes are this module's, not the command's - "
          "`audit-task.py` branches on E_LIVE/E_STALE and must not import a CLI "
          "to learn what they mean",
          (M.E_LIVE, M.E_STALE, M.E_USAGE, M.E_ERR) == (3, 4, 2, 1)
          and (_CMD.E_LIVE, _CMD.E_STALE) == (M.E_LIVE, M.E_STALE))
    check("b4 `main` stayed with the command - the half that is genuinely a CLI "
          "did NOT come down here, which is what keeps this module cheap enough "
          "for hooks/_config.py to load on every tool call",
          callable(getattr(_CMD, "main", None)) and not hasattr(M, "main"))
    check("b5 ...and neither did argparse. A hook resolves this file by path on "
          "every Edit; an argument parser it never calls is pure startup cost",
          not hasattr(M, "argparse") and hasattr(_CMD, "argparse"))

    # --- liveness -------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="audit-locks-")
    try:
        path = os.path.join(tmp, "index.lock")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "hostname": "thishost"}, fh)

        live, basis = M.judge({"pid": os.getpid(), "hostname": "thishost"},
                              path, host="thishost")
        check("j1 a running pid on THIS host is live at any age, and the basis "
              "names the pid rather than asserting it",
              live is True and str(os.getpid()) in basis, basis)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        live, basis = M.judge({"pid": dead.pid, "hostname": "thishost"}, path,
                              host="thishost")
        check("j2 a dead pid on this host is stale AT ONCE - no waiting for an "
              "age threshold, which is the whole point of liveness over age",
              live is False and "gone" in basis, basis)

        live, basis = M.judge({"pid": 1, "hostname": "elsewhere"}, path,
                              host="thishost")
        check("j3 another host falls back to the age rule and SAYS SO - the "
              "verdict is only as good as the basis printed beside it",
              "not this host" in basis and "threshold" in basis, basis)

        live, basis = M.judge({}, path, host="thishost")
        check("j4 no pid at all is not an error and not a crash: it is the age "
              "rule, named", "no pid recorded" in basis, basis)
        check("j5 a fresh no-pid lock reads LIVE, because every uncertainty "
              "resolves toward refusing - a false 'dead' costs two writers and a "
              "corrupted shard, a false 'alive' costs one deleted file",
              live is True)
        check("j6 a non-dict info does not raise - `read_lock` returns {} for a "
              "corrupt file and `judge` has to survive being handed it",
              M.judge("not a dict", path, host="h")[0] in (True, False))

        # --- names ------------------------------------------------------------
        check("n1 the two tiers the orchestrator uses are the two that are legal",
              M.valid_name("index") and M.valid_name("phase-P1"))
        _escapes = [n for n in ("..", "a/b", "phase-../x", "phase-a/b", "",
                                "phase-", "Index", "phase")
                    if M.valid_name(n)]
        check("n2 ...and nothing that could escape the lock directory is: %r"
              % (_escapes,), _escapes == [])

        # --- reading ----------------------------------------------------------
        check("r1 read_lock returns the dict it read", M.read_lock(path).get("pid")
              == os.getpid())
        bad = os.path.join(tmp, "bad.lock")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("r2 an unreadable or corrupt lock is {} rather than a raise - the "
              "panel badges a lock it cannot parse instead of 500ing",
              M.read_lock(bad) == {} and M.read_lock(os.path.join(tmp, "no")) == {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- acquire / release, the half that moved last --------------------------
    proj = tempfile.mkdtemp(prefix="audit-locks-proj-")
    try:
        if not shutil.which("git"):
            print("SKIP a* (git not installed)")
        else:
            subprocess.call(["git", "init", "-q", proj])
            # THE HOLDER'S PID IS THIS PROCESS, not 1. `a2` needs the holder to
            # be LIVE, and pid 1 is only live on POSIX -- on Windows it does not
            # exist, so `_pid_alive_windows` correctly answered "gone" and the
            # second session was told the lock looked ABANDONED instead of held.
            # That failed only on windows-latest, after green on ubuntu and here.
            # `os.getpid()` is alive by definition on every platform this runs on,
            # which is the property the case actually needs.
            live = os.getpid()
            lines = []
            code = M.acquire(proj, "index", note="n", session="s-A", pid=live,
                             out=lines.append)
            check("a1 acquire on a free lock returns 0 and says what it did",
                  code == 0 and any("acquired index" in x for x in lines), lines)
            lines = []
            code = M.acquire(proj, "index", note="n2", session="s-B", pid=live,
                             out=lines.append)
            check("a2 a second session is refused with E_LIVE and told WHO holds "
                  "it - a refusal with no holder is a dead end",
                  code == M.E_LIVE and any("s-A" in x for x in lines), lines)
            lines = []
            code = M.release(proj, "index", session="s-B", out=lines.append)
            check("a3 releasing someone else's lock is refused, which is how a "
                  "session that was taken over finds out at all",
                  code == M.E_LIVE and any("NOT yours" in x for x in lines), lines)
            check("a4 ...and the lock is still there afterwards. This is the case "
                  "that fails if the refusal ever becomes advisory",
                  os.path.exists(os.path.join(M.lock_dir(proj), "index.lock")))
            lines = []
            code = M.release(proj, "index", session="s-A", out=lines.append)
            check("a5 the owner releases it", code == 0
                  and not os.path.exists(os.path.join(M.lock_dir(proj),
                                                      "index.lock")))
            lines = []
            code = M.release(proj, "index", session="s-A", out=lines.append)
            check("a6 releasing what is not held is 0, not an error: a cleanup "
                  "path must be idempotent or every failure becomes two",
                  code == 0 and any("not held" in x for x in lines), lines)
            lines = []
            code = M.acquire(proj, "../escape", out=lines.append)
            check("a7 a bad name is refused before anything is created",
                  code == M.E_USAGE)
            check("a8 collect() over an empty dir is [] and does not raise",
                  M.collect(proj) == [])
    finally:
        shutil.rmtree(proj, ignore_errors=True)

    check("a9 outside a git repo lock_dir is None and acquire says so rather "
          "than writing somewhere arbitrary",
          M.lock_dir("/nonexistent-audit-locks-xyz") is None
          and M.acquire("/nonexistent-audit-locks-xyz", "index",
                        out=lambda *_a: None) == M.E_ERR)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__locks.py --selftest\n")
    raise SystemExit(2)
