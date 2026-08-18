#!/usr/bin/env python3
"""
The cases for `_doctor_hygiene.py` — what is HELD, and what is LEAKING.

`check_locks` is asserted through REAL lock files rather than a stubbed `_locks`,
because the thing worth pinning is that this check has no opinion of its own: it
prints whatever `_locks.judge` decided, basis and all. The two fixtures are a
lock held by THIS process (alive, by construction) and one naming a pid that
cannot be running — the pair is what tells "reports the live ones" from
"reports the dead ones", which a single lock cannot.

`check_local_artifacts` is graded WARNING throughout on purpose: a tracked
ledger is a privacy leak, not evidence of forgery. The journal is deliberately
absent from the list it checks, and that absence has its own case — it is the
opposite kind of artifact and must stay tracked.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_hygiene as M                        # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)
import _locks                                      # noqa: E402
import _loader                                     # noqa: E402


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


# --- cases --------------------------------------------------------------------
def _cases(check):
    import platform
    import tempfile

    cfgmod = _loader.load_hooks_config()
    have_git = bool(shutil.which("git"))
    if not have_git:
        print("SKIP git-dependent cases (git is not on PATH)")

    tmp = tempfile.mkdtemp(prefix="doctor-hygiene-")
    try:
        mrel = "docs/audit/audit-plan.json"

        # ------------------------------------------------------- check_locks
        rep = base.Report()
        M.check_locks(rep, None, tmp, mrel)
        check("dh1 with no git root the answer is 'no audit locks held' rather "
              "than silence - locks live in the git dir, so no repo really does "
              "mean no locks: %r" % (_detail(rep, "locks"),),
              _levels(rep, "locks") == ["OK"]
              and "no audit locks held" in _detail(rep, "locks"))

        rep = base.Report()
        M.check_local_artifacts(rep, tmp, {}, cfgmod, None, None)
        check("dh2 ...and hygiene says the same kind of thing: not a git "
              "repository means local artifacts cannot reach version control, "
              "which is an answer and not an absence: %r"
              % (_detail(rep, "hygiene"),),
              _levels(rep, "hygiene") == ["OK"]
              and "cannot reach version control" in _detail(rep, "hygiene"))

        if have_git:
            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for k, v in (("user.email", "p@example.com"), ("user.name", "P")):
                subprocess.run(["git", "-C", tmp, "config", k, v], check=True)
            with open(os.path.join(tmp, "a.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "i"], check=True,
                           stdout=subprocess.DEVNULL)

            rep = base.Report()
            M.check_locks(rep, tmp, tmp, mrel)
            check("dh3 a real repo holding no lock is still the ok line, not an "
                  "empty report: %r" % (_detail(rep, "locks"),),
                  _levels(rep, "locks") == ["OK"]
                  and "no audit locks held" in _detail(rep, "locks"))

            ldir = _locks.lock_dir(tmp)
            os.makedirs(ldir, exist_ok=True)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            def lock(name, pid):
                with open(os.path.join(ldir, name + ".lock"), "w",
                          encoding="utf-8") as fh:
                    json.dump({"pid": pid, "hostname": platform.node(),
                               "startedAt": now, "command": "/audit:phase"}, fh)

            lock("index", os.getpid())
            rep = base.Report()
            M.check_locks(rep, tmp, tmp, mrel)
            check("dh4 a lock held by a LIVE pid is an OK line that carries the "
                  "basis - 'another session holds this' is a claim the human is "
                  "about to act on: %r" % (_detail(rep, "locks"),),
                  _levels(rep, "locks") == ["OK"]
                  and "1 lock(s) held by a live run" in _detail(rep, "locks")
                  and "is running on this host" in _detail(rep, "locks"))

            lock("index", 999999)
            rep = base.Report()
            M.check_locks(rep, tmp, tmp, mrel)
            check("dh5 ...and one whose holder is gone is a WARNING offering "
                  "takeover. The pair is what separates 'reports the dead ones' "
                  "from 'reports the live ones' - one lock could not: %r"
                  % (_detail(rep, "locks"),),
                  _levels(rep, "locks") == ["WARNING"]
                  and "no live holder" in _detail(rep, "locks"))

            lock("index", os.getpid())
            lock("phase-P1", 999999)
            rep = base.Report()
            M.check_locks(rep, tmp, tmp, mrel)
            check("dh6 ...and with one of each, only the abandoned one is named. "
                  "Counted rather than found: a version reporting whichever it "
                  "saw last names the wrong lock: %r" % (_detail(rep, "locks"),),
                  _levels(rep, "locks") == ["WARNING"]
                  and "phase-P1" in _detail(rep, "locks")
                  and "index" not in _detail(rep, "locks"))
            shutil.rmtree(ldir, ignore_errors=True)

            # --------------------------------------- check_local_artifacts
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh7 a repo with none of the four artifacts yet says exactly "
                  "that, naming all four so the reader knows what was looked "
                  "for: %r" % (_detail(rep, "hygiene"),),
                  _levels(rep, "hygiene") == ["OK"]
                  and "no local artifacts yet" in _detail(rep, "hygiene"))

            ledger = os.path.join(tmp, ".claude", "usage")
            os.makedirs(ledger)
            with open(os.path.join(ledger, "2026-01.jsonl"), "w",
                      encoding="utf-8") as fh:
                fh.write("{}\n")
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh8 an untracked-but-unignored local dir is a WARNING that "
                  "names it and says a hook run makes it self-ignore: %r"
                  % (_detail(rep, "hygiene"),),
                  _levels(rep, "hygiene") == ["WARNING"]
                  and "not ignored yet: ledger" in _detail(rep, "hygiene"))

            with open(os.path.join(ledger, ".gitignore"), "w",
                      encoding="utf-8") as fh:
                fh.write("*\n")
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh9 ...and once it self-ignores, the row flips to the ok line "
                  "NAMING the artifacts it saw. THE OTHER-DIRECTION CASE: it is "
                  "what fails if the unprotected warning becomes unconditional: "
                  "%r" % (_detail(rep, "hygiene"),),
                  _levels(rep, "hygiene") == ["OK"]
                  and "stay out of git (ledger)" in _detail(rep, "hygiene"))

            subprocess.run(["git", "-C", tmp, "add", "-f", ".claude/usage"],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "leak"], check=True,
                           stdout=subprocess.DEVNULL)
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh10 a ledger COMMITTED before the marker existed is what an "
                  "ignore cannot reach, so it is reported here - counted, and "
                  "with one example named: %r" % (_detail(rep, "hygiene"),),
                  _levels(rep, "hygiene") == ["WARNING"]
                  and "local file(s) tracked in git" in _detail(rep, "hygiene"))

            pidfile = os.path.join(tmp, ".claude", "audit-panel.json")
            with open(pidfile, "w", encoding="utf-8") as fh:
                json.dump({"port": 1, "token": "t"}, fh)
            subprocess.run(["git", "-C", tmp, "add", "-f",
                            ".claude/audit-panel.json"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "pid"], check=True,
                           stdout=subprocess.DEVNULL)
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh11 the panel pidfile gets its OWN row, because its repair "
                  "is different: it holds a LIVE session token, so the fix is "
                  "rm --cached AND a restart to rotate it: %r"
                  % (_detail(rep, "hygiene"),),
                  "audit-panel.json) is TRACKED" in _detail(rep, "hygiene")
                  and "session token" in _detail(rep, "hygiene"))
            others = [r for r in rep.rows if r["check"] == "hygiene"
                      and "local file(s) tracked" in r["detail"]]
            check("dh12 ...and it is NOT also counted in the other row. The two "
                  "are partitioned rather than overlapping, which a presence "
                  "assertion on either alone would not catch: %r"
                  % ([r["detail"] for r in others],),
                  len(others) == 1
                  and "audit-panel.json" not in others[0]["detail"])

            journal = os.path.join(tmp, "docs", "audit", "journal")
            os.makedirs(journal)
            with open(os.path.join(journal, "2026-01.a.jsonl"), "w",
                      encoding="utf-8") as fh:
                fh.write("{}\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "j"], check=True,
                           stdout=subprocess.DEVNULL)
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, None, tmp)
            check("dh13 a TRACKED journal is never reported here. It is the "
                  "opposite kind of artifact and must stay in git - "
                  "`_doctor_trail` warns about the reverse - so its absence "
                  "from this list is a decision with a case on it: %r"
                  % (_detail(rep, "hygiene"),),
                  "journal" not in _detail(rep, "hygiene"))

            meta_led = {"meta": {"usage": {"ledgerDir": "custom/led"}}}
            os.makedirs(os.path.join(tmp, "custom", "led"))
            with open(os.path.join(tmp, "custom", "led", "x.jsonl"), "w",
                      encoding="utf-8") as fh:
                fh.write("{}\n")
            rep = base.Report()
            M.check_local_artifacts(rep, tmp, {}, cfgmod, meta_led, tmp)
            check("dh14 the ledger path comes from `meta.usage.ledgerDir` when "
                  "the manifest sets one, so a relocated ledger is still "
                  "checked rather than silently skipped: %r"
                  % (_detail(rep, "hygiene"),),
                  "not ignored yet" in _detail(rep, "hygiene")
                  and "ledger" in _detail(rep, "hygiene"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_hygiene.py --selftest\n")
    raise SystemExit(2)
