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

import errno
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time

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

        # --- an interrupted take ----------------------------------------------
        # A claim file with nothing in it names no session, no pid and no start,
        # so every identity rule falls through to the age rule - which answers
        # LIVE, and holds a lock the whole machine consults on behalf of a run
        # that never recorded itself.
        empty = os.path.join(tmp, "empty.lock")
        open(empty, "w").close()
        live, basis = M.judge(M.read_lock(empty), empty, host="thishost")
        check("e1 a claim file with nothing in it is NOT live: there is no "
              "holder here for the refusing bias to protect", live is False,
              basis)
        check("e2 ...and the basis says a take was interrupted rather than "
              "naming a session to go and wait for",
              "interrupted" in basis and "empty" in basis, basis)
        check("e3 ...while a claim that HAS content and cannot be parsed stays "
              "LIVE, because something wrote it - this is the one uncertainty "
              "that resolves away from refusing, and it must not widen",
              M.judge(M.read_lock(bad), bad, host="thishost")[0] is True)

        # --- the claim is written in one step ---------------------------------
        # A create and then a write is two steps, and a run killed between them
        # is what `e1` has to clean up after. The record goes into a sibling and
        # is linked onto the name, so the file either carries it or is not there.
        fresh = os.path.join(tmp, "fresh.lock")
        res = M._claim(fresh, {"sessionId": "s-1", "pid": 4242})
        check("e4 _claim answers in exactly one of three ways and a free name "
              "is `taken`: %r" % (res,),
              res == {"taken": True, "exists": False, "error": None})
        check("e5 ...and the record is IN the file the claim created, so there "
              "is no moment when the name exists carrying nothing",
              M.read_lock(fresh).get("sessionId") == "s-1"
              and os.path.getsize(fresh) > 0)
        res2 = M._claim(fresh, {"sessionId": "s-2"})
        check("e6 ...a name already claimed is `exists`, which is the caller's "
              "contention path and NOT an error - the two are different facts "
              "and are reported as two: %r" % (res2,),
              res2 == {"taken": False, "exists": True, "error": None})
        check("e6b ...and nothing of the refused taker reached the file",
              M.read_lock(fresh).get("sessionId") == "s-1")

        def _no_hard_links(_src, _dst):
            raise OSError(errno.EPERM, "this filesystem has no hard links")

        fallback = os.path.join(tmp, "fallback.lock")
        res3 = M._claim(fallback, {"sessionId": "s-3"}, link=_no_hard_links)
        check("e7 where hard links do not exist the claim still lands whole - a "
              "weaker lock beats the no lock at all that raising here would "
              "leave: %r" % (res3,),
              res3["taken"] is True
              and M.read_lock(fallback).get("sessionId") == "s-3")
        check("e8 the sibling the record was written in is gone afterwards. It "
              "is not a `.lock`, so nothing would ever have read it as one - a "
              "lock directory filling up with them is the bug: %r"
              % (sorted(n for n in os.listdir(tmp) if n.startswith(".claim-")),),
              [n for n in os.listdir(tmp) if n.startswith(".claim-")] == [])
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
            # AND ITS IDENTITY IS ITS OWN. The second session used to be handed
            # the same pid as the holder, which was invisible while `acquire`
            # never asked whose lock it was looking at; now that it asks, a
            # caller carrying the holder's pid IS the holder, and the case would
            # have been reading the re-entry answer while claiming to read a
            # refusal. `os.getppid()` is a live pid that is not this run's.
            code = M.acquire(proj, "index", note="n2", session="s-B",
                             pid=os.getppid(), wait=0, out=lines.append)
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

            # THE DOCUMENTED ESCAPE HAS TO CLEAR WHAT AN INTERRUPTED TAKE LEAVES.
            # An empty claim read as a fresh lock with no pid, which is LIVE: the
            # refusal told the operator to stop rather than offering the takeover,
            # so deleting a file by hand was the only way on - and this lock is
            # machine-wide, so every gate on the machine waited with it.
            stranded = os.path.join(M.lock_dir(proj), "phase-P7.lock")
            open(stranded, "w").close()
            lines = []
            code = M.acquire(proj, "phase-P7", session="s-C", pid=live,
                             out=lines.append)
            check("e9 acquiring over an empty claim OFFERS the takeover instead "
                  "of refusing as live - the escape a refusal names has to be "
                  "one that can clear what it found",
                  code == M.E_STALE and any("--takeover" in x for x in lines),
                  lines)
            check("e9b ...and no line invents a session to go looking for, "
                  "because an empty claim names nobody",
                  not any("an unknown session" in x for x in lines), lines)
            lines = []
            code = M.acquire(proj, "phase-P7", session="s-C", pid=live,
                             takeover=True, out=lines.append)
            check("e10 ...and the takeover clears it, which is the whole point: "
                  "a repair that needs a hand-deleted file is the class of "
                  "repair this plugin exists to remove",
                  code == 0
                  and M.read_lock(stranded).get("sessionId") == "s-C", lines)
            M.release(proj, "phase-P7", session="s-C", out=lambda *_a: None)
    finally:
        shutil.rmtree(proj, ignore_errors=True)

    check("a9 outside a git repo lock_dir is None and acquire says so rather "
          "than writing somewhere arbitrary",
          M.lock_dir("/nonexistent-audit-locks-xyz") is None
          and M.acquire("/nonexistent-audit-locks-xyz", "index",
                        out=lambda *_a: None) == M.E_ERR)

    # F260. `set-priority.py` refused with exit 3 and `pid N is running on this
    # host` — and that pid was the operator, mid take-lock / write / write /
    # release, which is the flow the lock exists for. `release` has always asked
    # whose it is; only `acquire` never did.
    check("o1 a lock carrying THIS session's id is ours",
          M.held_by_us({"sessionId": "sess-1", "pid": 4242},
                       session="sess-1", pid=None)["ours"] is True,
          repr(M.held_by_us({"sessionId": "sess-1"}, session="sess-1")))
    check("o2 ...and so is one carrying this session's PID, because a lock taken "
          "from Bash records $CLAUDE_CODE_SESSION_ID while a hook is handed "
          "session_id and $CLAUDE_PID is a third name for the same run - "
          "measured as three different values in one live session",
          M.held_by_us({"pid": 4242}, session="sess-1", pid=4242)["ours"] is True,
          repr(M.held_by_us({"pid": 4242}, session="sess-1", pid=4242)))
    check("o3 ...while a stranger's lock is NOT ours, which is what keeps o1 and "
          "o2 from being a rule that adopts every lock it finds",
          M.held_by_us({"sessionId": "somebody-else", "pid": 999},
                       session="sess-1", pid=4242)["ours"] is False,
          repr(M.held_by_us({"sessionId": "somebody-else", "pid": 999},
                            session="sess-1", pid=4242)))
    check("o4 ...and an empty or unreadable lock is not ours either - an "
          "unattributable lock must never be adopted, which is the same "
          "direction `release` refuses in",
          M.held_by_us({}, session="sess-1")["ours"] is False
          and M.held_by_us(None, session="sess-1")["ours"] is False,
          repr(M.held_by_us({}, session="sess-1")))
    check("o5 ...and the answer carries WHY, so the caller can print which of "
          "the two identities matched rather than asserting ownership bare",
          "sessionId" in M.held_by_us({"sessionId": "s"}, session="s")["why"]
          and "pid" in M.held_by_us({"pid": 7}, pid=7)["why"],
          repr([M.held_by_us({"sessionId": "s"}, session="s")["why"],
                M.held_by_us({"pid": 7}, pid=7)["why"]]))

    # Each of these builds its own fixtures and cleans them up, and each runs
    # through `stage` so a block whose fixture raises costs one named line
    # rather than every case after it. They are ordered cheapest first only for
    # the report; nothing in one is a fixture for another.
    #
    # THE BLOCK LABELS ARE NOT CASE IDS, deliberately. `stage` prints its label
    # on a FAIL line when a fixture raises, and a label spelled like the first
    # case inside it would let a reader - and anything grading this report by
    # name - take "the block never ran" for "that case went red", which are
    # opposite facts.
    _harness.stage(check, "q-block", _answer_cases)
    _harness.stage(check, "rr-block", _refusal_cases)
    _harness.stage(check, "hp-block", _holder_cases)
    _harness.stage(check, "tk-block", _takeover_cases)
    _harness.stage(check, "dd-block", _death_cases)
    _harness.stage(check, "rw-block", _row_cases)
    _harness.stage(check, "re-block", _reentry_cases)
    _harness.stage(check, "wt-block", _wait_cases)


# --- what a caller may do with the answer -------------------------------------
def _answer_cases(check):
    """`held` and `took`: proceeding and giving back stopped being one question."""
    check("q1 `held` covers BOTH ways of having the lock. A run that has just "
          "taken it and a run that already had it may write exactly alike, "
          "which is the point of answering re-entry instead of refusing it",
          M.held(0) is True and M.held(M.E_OURS) is True)
    check("q2 ...while `took` covers only the first. They were one question "
          "while there was a single way to hold a lock; an answer for re-entry "
          "made them two, and a call site left to decide that for itself is "
          "what put a lock on disk after every write the last time",
          M.took(0) is True and M.took(M.E_OURS) is False)
    check("q3 ...and neither reads a refusal as a hold, which is the direction "
          "that costs a corrupted shard rather than a stranded lock",
          not M.held(M.E_LIVE) and not M.held(M.E_STALE) and not M.held(M.E_ERR)
          and not M.took(M.E_LIVE) and not M.took(M.E_STALE))
    check("q4 ...and the re-entry answer is distinguishable from every other, "
          "or `took` has nothing to read: a code that collapsed onto 0 would "
          "make proceeding and releasing one answer again",
          M.E_OURS not in (0, M.E_LIVE, M.E_STALE, M.E_USAGE, M.E_ERR))
    check("q5 ...and the bound is a real one. Zero is the OLD behaviour, "
          "reachable by asking for it, and shipping it as the default is what "
          "turned an overlap as long as a file write into a stopped command",
          isinstance(M.WAIT_SECONDS, float) and M.WAIT_SECONDS > 0
          and 0 < M.POLL_SECONDS < M.WAIT_SECONDS)


# --- the sentence a declined release becomes ----------------------------------
def _refusal_cases(check):
    """A refused release is a value somebody reads, not a line nobody printed."""
    said = M.release_refusal(M.E_LIVE, "index")
    check("rr1 a declined release becomes a SENTENCE, and it says the thing a "
          "status code cannot: another session took this lock over while the "
          "work was running, so what was written since may have raced it",
          "NOT released" in said and "took it over" in said
          and "Re-read anything written since" in said, said)
    check("rr2 ...and it names where to look next. A refusal with no route on "
          "is a dead end, which is the rule `refusal` is held to one function "
          "over", "audit-lock.py status" in said, said)
    check("rr3 ...and it is built for a PAYLOAD, so it carries no hostname and "
          "no absolute path - the terminal lines name the host a live pid runs "
          "on, and those stay on the terminal",
          platform.node() not in said and os.sep not in said, said)
    check("rr4 ...and a code that is NOT a takeover does not borrow that "
          "sentence: a name the lock does not have and an unexplained failure "
          "are different facts and read as two",
          "took it over" not in M.release_refusal(M.E_USAGE, "index")
          and "took it over" not in M.release_refusal(M.E_ERR, "index"),
          repr([M.release_refusal(M.E_USAGE, "index"),
                M.release_refusal(M.E_ERR, "index")]))


# --- which pid goes INTO a claim ----------------------------------------------
def _holder_cases(check):
    """`judge` probes the recorded pid, so recording the wrong run is a false verdict."""
    prev = os.environ.get("CLAUDE_PID")
    os.environ.pop("CLAUDE_PID", None)
    try:
        check("hp1 a caller that takes the lock and gives it back before it "
              "returns IS this process, so this process is what the claim "
              "records - a durable pid there answers 'still running' on behalf "
              "of work that stopped",
              M._holder_pid(None, False) == os.getpid())
        check("hp2 ...while a command that EXITS still holding it records the "
              "run that invoked it. Its own pid dies before the next command "
              "starts, so recording that would make every lock taken from a "
              "shell read dead at once",
              M._holder_pid("4242", True) == 4242
              and M._holder_pid(4242, True) == 4242)
        check("hp3 ...and with no durable identity to name, that shape records "
              "NO pid and leaves the age rule to answer - the fallback it has "
              "always had - rather than inventing a liveness nothing supports",
              M._holder_pid(None, True) is None)
        os.environ["CLAUDE_PID"] = "4243"
        check("hp4 ...which is where the environment is read, and only there: "
              "$CLAUDE_PID names the run a handed-off lock belongs to, and a "
              "lock this process hands back itself is not that run",
              M._holder_pid(None, True) == 4243
              and M._holder_pid(None, False) == os.getpid())
        os.environ["CLAUDE_PID"] = "not a pid"
        check("hp5 ...and junk there is not a pid. The age rule answers again, "
              "rather than a crash or a number that would probe as whatever "
              "unrelated process happens to hold it",
              M._holder_pid(None, True) is None)
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PID", None)
        else:
            os.environ["CLAUDE_PID"] = prev


# --- the takeover: who gets the name, and what the row may say ----------------
def _takeover_cases(check):
    """The create decides, and the row is bounded by what actually happened."""
    tmp = tempfile.mkdtemp(prefix="audit-locks-takeover-")
    try:
        path = os.path.join(tmp, "index.lock")
        check("tk0 a name with nothing at it has no stamp, which is how "
              "'there was no claim to displace' is told from 'the claim "
              "changed under me'", M._claim_stamp(path) is None)
        M._write_lock(path, {"sessionId": "s-OLD", "note": "old"})
        first = M._claim_stamp(path)
        M._write_lock(path, {"sessionId": "s-NEW", "note": "new"})
        check("tk0b ...and a claim that was REPLACED does not stamp as the one "
              "it replaced. That is the whole test: the file judged a moment "
              "ago has to be the file about to be removed",
              first is not None and M._claim_stamp(path) != first,
              repr([first, M._claim_stamp(path)]))

        os.unlink(path)
        M._write_lock(path, {"sessionId": "s-OLD", "note": "old"})
        stamp = M._claim_stamp(path)
        res = M._take_over(path, {"sessionId": "s-WIN"}, stamp,
                           {"takenOverBasis": "the holder is gone"})
        check("tk1 THE ALLOW CASE. A takeover whose claim is still the one that "
              "was judged goes through and says it displaced something - a test "
              "tightened until no takeover can ever land is a recovery door "
              "welded shut, which is the other half of this being right: %r"
              % (res,),
              res["taken"] is True and res["displaced"] is True
              and M.read_lock(path).get("sessionId") == "s-WIN"
              and M.read_lock(path).get("takenOverBasis") == "the holder is gone")

        os.unlink(path)
        M._write_lock(path, {"sessionId": "s-OLD", "note": "old"})
        stale = M._claim_stamp(path)
        M._write_lock(path, {"sessionId": "s-WINNER", "note": "got there first"})
        res = M._take_over(path, {"sessionId": "s-LOSER"}, stale,
                           {"takenOverBasis": "judged a moment ago"})
        check("tk2 ...while a claim that is no longer the one that was judged "
              "is neither removed nor written over. Read, judge, then write "
              "let both takers pass one judgement, and the later write replaced "
              "a claim that was by then LIVE - the state this lock exists to "
              "make impossible, reached through the door built for recovery: %r"
              % (res,),
              res["taken"] is False and res["exists"] is True
              and res["displaced"] is False
              and M.read_lock(path).get("sessionId") == "s-WINNER")

        os.unlink(path)
        M._write_lock(path, {"sessionId": "s-LEAVING"})
        stamp = M._claim_stamp(path)
        os.unlink(path)
        res = M._take_over(path, {"sessionId": "s-NEXT"}, stamp,
                           {"takenOverBasis": "the holder is gone",
                            "takenOverFrom": {"sessionId": "s-LEAVING"}})
        got = M.read_lock(path)
        check("tk3 ...and a holder that let go BY ITSELF was displaced by "
              "nobody, so the row carries none of it. A basis for an event no "
              "one observed is worse than no basis, because it outlives every "
              "reader who could have contradicted it: %r" % (res,),
              res["taken"] is True and res["displaced"] is False
              and "takenOverBasis" not in got and "takenOverFrom" not in got,
              repr(got))

        os.unlink(path)
        M._write_lock(path, {"sessionId": "s-HOLD"})
        res = M._take_over(path, {"sessionId": "s-LATE"}, None,
                           {"takenOverBasis": "b"})
        check("tk4 ...and a takeover with nothing stamped removes nothing. "
              "`None` says no claim was judged, and unlinking on it would be a "
              "delete decided by the absence of evidence: %r" % (res,),
              res["taken"] is False and res["displaced"] is False
              and M.read_lock(path).get("sessionId") == "s-HOLD")

        os.unlink(path)
        M._write_lock(path, {"sessionId": "s-STALE"})
        stamp = M._claim_stamp(path)

        def _sneak_in(src, dst):
            """Another run claims the name between the unlink and the link."""
            M._write_lock(dst, {"sessionId": "s-FASTER"})
            return os.link(src, dst)

        res = M._take_over(path, {"sessionId": "s-LOSER"}, stamp,
                           {"takenOverBasis": "b"}, link=_sneak_in)
        check("tk5 ...and whoever loses the create is TOLD it lost instead of "
              "writing over the winner. The create is the exclusivity test here "
              "exactly as it is for a free name, which is what leaves no window "
              "to lose: %r" % (res,),
              res["taken"] is False and res["exists"] is True
              and res["displaced"] is False
              and M.read_lock(path).get("sessionId") == "s-FASTER")

        check("tk6 the row names a holder that was named, with the fields the "
              "claim actually carried and never a key it did not",
              M._displaced_record({"sessionId": "s", "note": "n", "junk": 1})
              == {"sessionId": "s", "note": "n"},
              repr(M._displaced_record({"sessionId": "s", "note": "n",
                                        "junk": 1})))
        empty = os.path.join(tmp, "empty.lock")
        open(empty, "w").close()
        bad = os.path.join(tmp, "bad.lock")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("tk7 ...and a claim that named NOBODY yields nothing to name, "
              "rather than an empty mapping under a key meaning 'the run this "
              "was taken from' - which reads to a later reader as a run to go "
              "and find", M._displaced_record({}) == {})
        check("tk8 ...so it is DESCRIBED instead, and the description keeps "
              "apart what the rest of this module refuses to collapse: a take "
              "that never recorded itself is not bytes that will not parse, "
              "which is why one of them reads dead and the other stays live",
              M._unattributed_claim({}, empty) != M._unattributed_claim({}, bad)
              and "did not finish" in M._unattributed_claim({}, empty)
              and "never named" in M._unattributed_claim({}, bad),
              repr([M._unattributed_claim({}, empty),
                    M._unattributed_claim({}, bad)]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the claim stops being true when the run stops ----------------------------
def _death_cases(check):
    """A killed run's lock reads dead at once, because it recorded its own pid."""
    if not shutil.which("git"):
        _harness.skip(check, "dd1 a killed run's claim reads dead",
                      "git provides the shared directory a lock lives in", True)
        return
    proj = tempfile.mkdtemp(prefix="audit-locks-death-")
    try:
        subprocess.call(["git", "init", "-q", proj])
        source = ("import sys\n"
                  "sys.path.insert(0, %r)\n"
                  "import _locks\n"
                  "sys.exit(_locks.acquire(%r, 'phase-P9', note='a gate',\n"
                  "                        session='s-CHILD',\n"
                  "                        out=lambda *a, **k: None))\n"
                  % (os.path.dirname(os.path.abspath(M.__file__)), proj))
        child = subprocess.run([sys.executable, "-c", source],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        path = os.path.join(M.lock_dir(proj), "phase-P9.lock")
        info = M.read_lock(path)
        live, basis = M.judge(info, path)
        check("dd1 a run that took the lock through the library and then "
              "stopped leaves a claim that reads DEAD at once. The pid in a "
              "claim is the one whose death ends the hold; record one that "
              "outlives the gate and a stopped run holds every lock this "
              "machine consults until the age threshold runs out",
              child.returncode == 0 and live is False and "gone" in basis,
              "%r %r %r" % (child.returncode, info, basis))
        check("dd1b ...because the pid it recorded is its OWN - neither this "
              "process's nor none at all. The age rule is the answer for a "
              "claim that names nobody, and it was answering here for claims "
              "that named a run no probe could reach",
              info.get("pid") not in (None, os.getpid()), repr(info))
    finally:
        shutil.rmtree(proj, ignore_errors=True)


# --- what `--takeover` writes into the claim it replaces ----------------------
def _row_cases(check):
    """The row records what happened, and says which kind of nothing it found."""
    if not shutil.which("git"):
        _harness.skip(check, "rw1 the takeover row is read back off disk",
                      "git provides the shared directory a lock lives in", True)
        return
    proj = tempfile.mkdtemp(prefix="audit-locks-row-")
    try:
        subprocess.call(["git", "init", "-q", proj])
        quiet = lambda *_a, **_k: None                      # noqa: E731
        ld = M.lock_dir(proj)
        os.makedirs(ld, exist_ok=True)
        path = os.path.join(ld, "phase-P1.lock")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        M._write_lock(path, {"sessionId": "s-DEAD", "hostname": platform.node(),
                             "pid": dead.pid, "note": "crashed",
                             "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                        time.gmtime())})
        code = M.acquire(proj, "phase-P1", session="s-NEXT", pid=os.getpid(),
                         takeover=True, out=quiet)
        got = M.read_lock(path)
        check("rw1 a takeover that displaced a NAMED holder names it, and "
              "carries the basis it was judged on - the sentence that makes the "
              "seizure checkable by whoever reads the claim next",
              code == 0 and got.get("takenOverFrom", {}).get("sessionId")
              == "s-DEAD" and got.get("takenOverBasis")
              and "takenOverFound" not in got, repr(got))

        os.unlink(path)
        open(path, "w").close()
        code = M.acquire(proj, "phase-P1", session="s-NEXT2", pid=os.getpid(),
                         takeover=True, out=quiet)
        got = M.read_lock(path)
        check("rw2 ...while a claim that named nobody is DESCRIBED, and the key "
              "meaning 'the run this was taken from' is absent rather than "
              "empty. An empty mapping there reads as a run to go and find",
              code == 0 and "takenOverFrom" not in got
              and "did not finish" in (got.get("takenOverFound") or ""),
              repr(got))

        os.unlink(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        code = M.acquire(proj, "phase-P1", session="s-NEXT3", pid=os.getpid(),
                         takeover=True, out=quiet)
        got = M.read_lock(path)
        check("rw3 ...and bytes that will not parse are described as THAT and "
              "not as the same thing. This module reads one of those dead and "
              "the other live, and one word for both would erase the "
              "difference it acts on",
              code == 0 and "never named" in (got.get("takenOverFound") or ""),
              repr(got))
    finally:
        shutil.rmtree(proj, ignore_errors=True)


# --- a lock this run already holds --------------------------------------------
def _reentry_cases(check):
    """Answered, never waited for - and never extended to a stranger's claim."""
    if not shutil.which("git"):
        _harness.skip(check, "re1 re-entry is answered rather than waited out",
                      "git provides the shared directory a lock lives in", True)
        return
    proj = tempfile.mkdtemp(prefix="audit-locks-reentry-")
    try:
        subprocess.call(["git", "init", "-q", proj])
        quiet = lambda *_a, **_k: None                      # noqa: E731
        M.acquire(proj, "index", note="outer hold", session="s-SAME",
                  pid=os.getppid(), out=quiet)
        path = os.path.join(M.lock_dir(proj), "index.lock")
        before = M._claim_stamp(path)

        lines = []
        started = time.monotonic()
        code = M.acquire(proj, "index", note="inner", session="s-SAME",
                         pid=os.getppid(), wait=9.0, out=lines.append)
        spent = time.monotonic() - started
        check("re1 a lock this run already holds is ANSWERED, and answered "
              "before anything is waited for. A command that takes a lock and "
              "calls another command that takes the same one would otherwise "
              "spend the whole bound waiting for itself and then be refused by "
              "its own claim",
              code == M.E_OURS and spent < 1.0,
              "exit %s after %.3fs" % (code, spent))
        check("re2 ...and nothing was taken: the claim on disk is still the one "
              "the outer hold wrote, down to the file it is",
              M._claim_stamp(path) == before
              and M.read_lock(path).get("note") == "outer hold",
              repr(M.read_lock(path)))
        check("re3 ...and the line carries the half a status cannot - that "
              "whatever took the lock still needs it, so this call has nothing "
              "to give back",
              any("already yours" in x for x in lines)
              and any("leave the release" in x for x in lines), repr(lines))

        lines = []
        code = M.acquire(proj, "index", session="s-OTHER", pid=os.getpid(),
                         wait=0, out=lines.append)
        check("re4 THE ALLOW CASE. A DIFFERENT run asking for the same lock is "
              "refused and told who has it. A re-entry answer widened until it "
              "adopts a stranger's claim is both runs believing they hold one "
              "lock, which is the single thing this module may never do",
              code == M.E_LIVE and any("s-SAME" in x for x in lines),
              "exit %s %r" % (code, lines))
        M.release(proj, "index", session="s-SAME", out=quiet)
    finally:
        shutil.rmtree(proj, ignore_errors=True)


# --- the bound a contended lock is waited out for -----------------------------
def _unlink_quietly(path):
    """A holder letting go, from a timer: the file is the whole of the claim."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _wait_cases(check):
    """Ordinary overlap is absorbed; an answer waiting cannot change is immediate."""
    if not shutil.which("git"):
        _harness.skip(check, "wt1 the bound is measured against a real lock",
                      "git provides the shared directory a lock lives in", True)
        return
    proj = tempfile.mkdtemp(prefix="audit-locks-wait-")
    try:
        subprocess.call(["git", "init", "-q", proj])
        quiet = lambda *_a, **_k: None                      # noqa: E731
        path = os.path.join(M.lock_dir(proj), "index.lock")
        M.acquire(proj, "index", note="a structural write", session="s-HOLD",
                  pid=os.getppid(), out=quiet)

        started = time.monotonic()
        code = M.acquire(proj, "index", session="s-W1", pid=os.getpid(),
                         wait=0, out=quiet)
        instant = time.monotonic() - started
        check("wt1 zero asks for the answer the instant the name exists, and "
              "gets it. That is what this command did before executors ran side "
              "by side, and a caller that wants a refusal rather than a delay "
              "still says so",
              code == M.E_LIVE and instant < 1.0,
              "exit %s after %.3fs" % (code, instant))

        started = time.monotonic()
        code = M.acquire(proj, "index", session="s-W1", pid=os.getpid(),
                         wait=0.4, out=quiet)
        waited = time.monotonic() - started
        check("wt2 ...and a bound is PAID before the refusal is printed, which "
              "is the whole of the concession: refusing the moment the name "
              "exists is right on a machine running one command at a time, and "
              "this product spawns executors in parallel by design",
              code == M.E_LIVE and waited >= 0.35,
              "exit %s after %.3fs" % (code, waited))

        letting_go = threading.Timer(0.3, _unlink_quietly, args=(path,))
        letting_go.start()
        started = time.monotonic()
        try:
            code = M.acquire(proj, "index", note="the waiter's own",
                             session="s-W2", pid=os.getpid(), out=quiet)
        finally:
            letting_go.cancel()
        outlasted = time.monotonic() - started
        check("wt3 ...so a holder that lets go INSIDE the bound is waited out "
              "rather than refused, on the default this ships with. This is "
              "the case that goes red if the bound is taken back to zero, and "
              "the reason it does not pass a bound of its own",
              code == 0, "exit %s after %.3fs" % (code, outlasted))
        M.release(proj, "index", session="s-W2", out=quiet)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        M._write_lock(path, {"hostname": platform.node(), "pid": dead.pid,
                             "note": "crashed",
                             "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                        time.gmtime())})
        started = time.monotonic()
        code = M.acquire(proj, "index", session="s-W3", pid=os.getpid(),
                         wait=9.0, out=quiet)
        gone = time.monotonic() - started
        check("wt4 ...while an answer no amount of waiting can change is given "
              "at once: a holder that is not alive will not become any more "
              "gone, and a bound spent on it is a delay bought for nothing",
              code == M.E_STALE and gone < 1.0,
              "exit %s after %.3fs" % (code, gone))
    finally:
        shutil.rmtree(proj, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__locks.py --selftest\n")
    raise SystemExit(2)
