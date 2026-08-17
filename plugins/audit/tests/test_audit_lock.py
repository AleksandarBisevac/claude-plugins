#!/usr/bin/env python3
"""
The cases for `scripts/audit-lock.py`, moved out of it - the entry-point shape.

Hyphenated, so the file name substitutes underscores and the module comes through
`_loader.load_script`; see `test_migrate_manifest.py` for that rule. `M` is the
module under test.

ONE EXPRESSION NAMED THE FILE IT LIVED IN. `a-mtime` needs "a real file with a real
mtime" to prove `_age_minutes` falls back to the filesystem when `startedAt` is
junk, and inline it passed `__file__`. Here that would be this test file, which is
merely A file rather than THE file the case is about; it reads `M.__file__`, the
module under test's own source, which is what the expression always meant. (The
sibling `j6` case above it once had the OPPOSITE problem - it used `__file__` as
"a file with a RECENT mtime" and went red on an unmodified checkout - and was
already rewritten to build a tempfile and set its mtime explicitly. `a-mtime` only
asserts the age is positive, which holds for any file whose mtime is in the past.)

The `age_cases` group runs twice, the second time under TZ=Europe/Belgrade, and
restores `TZ` in `finally`. That matters more here than it did inline: `_harness.run`
CATCHES an escaping exception and carries on, so a leaked TZ would be read by
whatever ran next in the same process.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("audit-lock.py", modname="audit_lock")


# --- cases --------------------------------------------------------------------
def _cases(check):
    def run(argv, project):
        lines = []
        code = M.main(argv + ["--project", project], out=lines.append)
        return code, "\n".join(lines)

    # A pid that is definitely gone: spawn one and wait for it.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    dead_pid = dead.pid

    # (l) liveness probe
    check("l1 our own pid reads alive", M.pid_alive(os.getpid()) is True)
    check("l2 an exited pid reads dead", M.pid_alive(dead_pid) is False)
    check("l3 pid 0 is unknowable, not a verdict", M.pid_alive(0) is None)
    check("l4 garbage pid is unknowable", M.pid_alive("nope") is None)

    # (j) judge -- the whole point: liveness beats age in both directions
    here = platform.node()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 95 * 60))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    live, basis = M.judge({"hostname": here, "pid": os.getpid(),
                           "startedAt": old}, "")
    check("j1 a 95-min run with a live pid is LIVE (false stale fixed)", live is True)
    check("j1b and says why", "is running on this host" in basis)
    live, basis = M.judge({"hostname": here, "pid": dead_pid, "startedAt": now}, "")
    check("j2 a 1-min run with a dead pid is stale at once (false fresh fixed)",
          live is False)
    check("j2b and says why", "is gone on this host" in basis)
    live, basis = M.judge({"hostname": here, "startedAt": old}, "")
    check("j3 no pid -> the old age rule, and it says so", live is False)
    check("j3b basis names the threshold", "threshold 60" in basis)
    live, _ = M.judge({"hostname": here, "startedAt": now}, "")
    check("j4 no pid, young -> live", live is True)
    live, basis = M.judge({"hostname": "somewhere-else", "pid": os.getpid(),
                           "startedAt": now}, "")
    check("j5 another host's pid is not probed",
          live is True and "not this host" in basis)
    live, _ = M.judge({"hostname": "somewhere-else", "pid": os.getpid(),
                       "startedAt": old}, "")
    check("j5b another host falls back to age", live is False)
    # j6 used `__file__` as "a file with a recent mtime", so it only passed on a day
    # someone edited audit-lock.py — it went red the first time the full suite ran
    # against an unmodified checkout. A test whose verdict depends on the clock
    # relative to a source file's mtime asserts nothing you can rely on.
    _fd, _mt = tempfile.mkstemp(prefix="audit-lock-mtime-")
    os.close(_fd)
    check("j6 an unreadable lock with a fresh file is not a licence to seize it",
          M.judge({}, _mt)[0] is True)
    os.utime(_mt, (time.time() - 95 * 60, time.time() - 95 * 60))
    check("j6b an unreadable lock falls back to the file's own age",
          M.judge({}, _mt)[0] is False)
    os.unlink(_mt)
    check("j6c and a lock whose file is gone reads live, never seizable",
          M.judge({}, os.path.join(tempfile.gettempdir(), "no-such.lock"))[0] is True)

    # (a) age math -- the number the whole threshold rests on. Pinned in a
    # non-UTC, DST-observing zone too: CI runners are UTC, so a local-time bug
    # would pass there and be exactly 60 minutes wrong for a user in Europe.
    def age_cases(label):
        for mins in (0, 30, 59, 61, 95, 1440):
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                  time.gmtime(time.time() - mins * 60))
            got = M._age_minutes({"startedAt": stamp}, "")
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
          M._age_minutes({"startedAt": "not a date"}, M.__file__) > 0)

    # (n) name validation -- a lock name reaches the filesystem
    check("n1 index", M.valid_name("index"))
    check("n2 phase-P1", M.valid_name("phase-P1"))
    check("n3 traversal rejected", not M.valid_name("phase-../../etc/passwd"))
    check("n4 separator rejected", not M.valid_name("phase-a/b"))
    check("n5 bare id rejected", not M.valid_name("P1"))
    check("n6 empty phase id rejected", not M.valid_name("phase-"))

    # (c) the CLI, against a real git repo
    tmp = tempfile.mkdtemp(prefix="audit-lock-")
    try:
        if not shutil.which("git"):
            print("SKIP c* (git not installed)")
        else:
            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ld = M.lock_dir(tmp)
            check("c0 lock dir resolves inside the git dir",
                  ld and ld.endswith("audit-locks") and ".git" in ld)

            code, txt = run(["acquire", "phase-P1", "--note", "phase P1",
                             "--session", "sess-A", "--pid", str(os.getpid())], tmp)
            check("c1 first acquire succeeds", code == 0 and "acquired" in txt)
            check("c1b lock records the pid it was given",
                  M.read_lock(os.path.join(ld, "phase-P1.lock")).get("pid")
                  == os.getpid())

            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c2 a live holder refuses (exit 3)", code == M.E_LIVE)
            check("c2b and names the holder", "sess-A" in txt)
            check("c2c and does not offer a takeover", "--takeover" not in txt)

            code, txt = run(["acquire", "index", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c3 a different lock is free (two phases run in parallel)",
                  code == 0)
            code, _ = run(["release", "index", "--session", "sess-B"], tmp)
            check("c3b released", code == 0)

            # Age alone must not unlock a live run -- the C1 defect, end to end.
            p1 = os.path.join(ld, "phase-P1.lock")
            info = M.read_lock(p1)
            info["startedAt"] = old
            M._write_lock(p1, info)
            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c4 a 95-min-old LIVE run still refuses", code == M.E_LIVE)

            info["pid"] = dead_pid
            M._write_lock(p1, info)
            code, txt = run(["acquire", "phase-P1", "--session", "sess-B",
                             "--pid", str(os.getpid())], tmp)
            check("c5 a dead holder offers takeover (exit 4)", code == M.E_STALE)
            check("c5b and says how", "--takeover" in txt)
            check("c5c but has not seized it yet",
                  M.read_lock(p1).get("sessionId") == "sess-A")

            code, txt = run(["acquire", "phase-P1", "--session", "sess-B", "--takeover",
                             "--pid", str(os.getpid())], tmp)
            check("c6 --takeover seizes it", code == 0 and "took over" in txt)
            after = M.read_lock(p1)
            check("c6b now owned by B", after.get("sessionId") == "sess-B")
            check("c6c and records who it took from",
                  after.get("takenOverFrom", {}).get("sessionId") == "sess-A")

            # The loser learns it lost -- today it silently deletes the winner's lock.
            code, txt = run(["release", "phase-P1", "--session", "sess-A"], tmp)
            check("c7 the taken-over session cannot release (exit 3)",
                  code == M.E_LIVE)
            check("c7b and is told it was taken over", "taken over" in txt)
            check("c7c the winner's lock survives", os.path.exists(p1))

            code, txt = run(["status"], tmp)
            check("c8 status lists it", "phase-P1" in txt and "LIVE" in txt)
            code, txt = run(["status", "--json"], tmp)
            check("c8b --json parses",
                  json.loads(txt)["locks"][0]["name"] == "phase-P1")
            check("c8c and carries the basis", json.loads(txt)["locks"][0]["basis"])

            code, _ = run(["release", "phase-P1", "--session", "sess-B"], tmp)
            check("c9 the owner releases", code == 0)
            check("c9b lock is gone", not os.path.exists(p1))
            code, txt = run(["release", "phase-P1", "--session", "sess-B"], tmp)
            check("c9c releasing twice is not an error", code == 0)

            code, txt = run(["acquire", "phase-../escape", "--session", "s"], tmp)
            check("c10 a traversing name is a usage error", code == M.E_USAGE)

            # A lock written by the old prose (no pid) must still work.
            M._write_lock(p1, {"hostname": here, "startedAt": now, "note": "legacy"})
            code, _ = run(["acquire", "phase-P1", "--session", "sess-C"], tmp)
            check("c11 a legacy pid-less lock is honoured", code == M.E_LIVE)
            M._write_lock(p1, {"hostname": here, "startedAt": old, "note": "legacy"})
            code, _ = run(["acquire", "phase-P1", "--session", "sess-C"], tmp)
            check("c11b and goes stale on age, as it always did", code == M.E_STALE)
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
                      "pid" not in M.read_lock(os.path.join(ld, "phase-P9.lock")))
            finally:
                if saved is not None:
                    os.environ["CLAUDE_PID"] = saved

        code, _ = run(["status"], os.path.join(tmp, "not-a-repo"))
        check("c13 status outside a repo is quiet, not an error", code == 0)
        code, txt = run(["acquire", "index"], os.path.join(tmp, "not-a-repo"))
        check("c13b acquire outside a repo errors clearly",
              code == M.E_ERR and "not a git repository" in txt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # argparse writes its usage text to stderr on an invalid choice; swallow it so
    # a passing suite prints only its own lines.
    with open(os.devnull, "w") as _null, contextlib.redirect_stderr(_null):
        _rc = M.main(["frobnicate"], out=lambda *_: None)
    check("m1 an unknown command is a usage error", _rc == M.E_USAGE)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_lock.py --selftest\n")
    raise SystemExit(2)
