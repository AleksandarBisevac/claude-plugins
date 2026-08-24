#!/usr/bin/env python3
"""
The cases for `_doctor_trail.py` — has anything run here, and does what it
wrote still hold?

The distinction every case here is drawn against: NEVER STARTED and STOPPED are
different diagnoses, and only one of them is a problem. A ledger directory that
does not exist is not "exists but holds no rows"; a journal switched off with
rows on disk is not the same as a journal switched off with none. Both of those
were real defects, and both are pinned below in the shape that separates them.

Ages are set with `os.utime` rather than waited for, and always on BOTH sides of
`RECENT_DAYS`: a fixture only older than the threshold cannot tell `>` from
`>= 0`, and one only younger cannot tell the branch fires at all.

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
import _doctor_trail as M                          # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _age(path, days):
    when = time.time() - days * 86400
    os.utime(path, (when, when))


# --- cases --------------------------------------------------------------------
def _cases(check):

    cfgmod = _loader.load_hooks_config()
    ul = _loader.load_script("usage_ledger.py", modname="dt_ledger")
    tmp = _harness.fixture_root("doctor-trail-")
    try:
        mrel = "docs/audit/audit-plan.json"
        os.makedirs(os.path.join(tmp, "docs", "audit"))

        # -------------------------------------------------- check_hooks_fired
        rep = base.Report()
        M.check_hooks_fired(rep, tmp, {}, cfgmod)
        check("dt1 no hook state at all is a WARNING whose FIX names the likely "
              "cause - an uninstalled or disabled plugin looks identical to a "
              "healthy one from inside the repo: %r" % (_detail(rep, "hooks"),),
              _levels(rep, "hooks") == ["WARNING"]
              and "nothing here proves" in _detail(rep, "hooks"))

        state = os.path.join(tmp, ".claude", "state")
        os.makedirs(state)
        fresh = os.path.join(state, "session.json")
        older = os.path.join(state, "other.json")
        for p in (fresh, older):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}\n")

        _age(fresh, 1.0)
        _age(older, 30.0)
        rep = base.Report()
        M.check_hooks_fired(rep, tmp, {}, cfgmod)
        check("dt2 the NEWEST file decides, not the oldest: one 30-day file "
              "beside a 1-day one is a healthy repo. The two ages are what make "
              "`max` and `min` disagree here: %r" % (_detail(rep, "hooks"),),
              _levels(rep, "hooks") == ["OK"]
              and "2 state file(s)" in _detail(rep, "hooks"))

        _age(fresh, 6.5)
        rep = base.Report()
        M.check_hooks_fired(rep, tmp, {}, cfgmod)
        check("dt3 6.5 days is still inside RECENT_DAYS and stays OK - the "
              "younger half of the threshold, without which a moved threshold "
              "has nowhere to show: %r" % (_detail(rep, "hooks"),),
              _levels(rep, "hooks") == ["OK"])

        _age(fresh, 7.5)
        rep = base.Report()
        M.check_hooks_fired(rep, tmp, {}, cfgmod)
        check("dt4 ...and 7.5 days is outside it, warning that the state is old "
              "while saying it is harmless if you have been away: %r"
              % (_detail(rep, "hooks"),),
              _levels(rep, "hooks") == ["WARNING"]
              and "days old" in _detail(rep, "hooks"))

        # ------------------------------------------------------ check_ledger
        rep = base.Report()
        M.check_ledger(rep, tmp, {"usage": {"enabled": False}}, mrel)
        check("dt5 metering switched off in config is an OK line - the user's "
              "own switch is never a defect: %r" % (_detail(rep, "usage ledger"),),
              _levels(rep, "usage ledger") == ["OK"]
              and "disabled in config" in _detail(rep, "usage ledger"))

        rep = base.Report()
        M.check_ledger(rep, tmp, {}, mrel)
        check("dt6 a ledger directory that was never created reads 'no ledger "
              "yet' and NAMES where it would live. F-E2: it used to say '<path> "
              "exists but holds no rows', asserting the existence of a directory "
              "nothing ever made: %r" % (_detail(rep, "usage ledger"),),
              "no ledger yet" in _detail(rep, "usage ledger")
              and os.path.join(tmp, ".claude", "usage")
              in _detail(rep, "usage ledger"))
        check("dt7 ...and never uses the word 'exists' about it, which is the "
              "half of F-E2 a presence assertion would miss",
              "exists" not in _detail(rep, "usage ledger"))

        ledger = os.path.join(tmp, ".claude", "usage")
        ul.ensure_ledger_dir(ledger)
        rep = base.Report()
        M.check_ledger(rep, tmp, {}, mrel)
        check("dt8 a directory that IS there but holds no rows gets the other "
              "sentence - the two branches say different things because they "
              "are different diagnoses: %r" % (_detail(rep, "usage ledger"),),
              "exists but holds no rows yet" in _detail(rep, "usage ledger"))

        ul.append_rows(ledger, [{"ts": "2026-01-01T00:00:00Z", "taskId": "P1.1",
                                 "author": "a@example.com", "model": "m",
                                 "inputTokens": 1, "outputTokens": 1}])
        rep = base.Report()
        M.check_ledger(rep, tmp, {}, mrel)
        check("dt9 ...and rows on disk are an OK line counting the FILES that "
              "hold them: %r" % (_detail(rep, "usage ledger"),),
              _levels(rep, "usage ledger") == ["OK"]
              and "1 ledger file(s)" in _detail(rep, "usage ledger"))

        # ----------------------------------------------------- check_journal
        rep = base.Report()
        M.check_journal(rep, tmp, {"journal": {"enabled": False}}, cfgmod, None)
        check("dt10 a journal switched off with NO rows on disk is an ok line - "
              "that is what every repo looks like before its first write: %r"
              % (_detail(rep, "journal"),),
              _levels(rep, "journal") == ["OK"]
              and "disabled in config" in _detail(rep, "journal"))

        rep = base.Report()
        M.check_journal(rep, tmp, {}, cfgmod, None)
        check("dt11 ...and enabled with none written is a different ok line, "
              "naming the directory that does not exist: %r"
              % (_detail(rep, "journal"),),
              _levels(rep, "journal") == ["OK"]
              and "no writes recorded yet" in _detail(rep, "journal"))

        _journal_io.append(tmp, {"action": "task.complete", "actor": "probe",
                                 "ts": "2026-01-01T00:00:00Z",
                                 "details": {"taskId": "P1.1"}})
        rep = base.Report()
        M.check_journal(rep, tmp, {"journal": {"enabled": False}}, cfgmod, None)
        check("dt12 a journal switched off WITH rows on disk is a WARNING: the "
              "trail was running and someone turned it off, and grading that "
              "identically to 'never used' is how completion records quietly "
              "stopped being written: %r" % (_detail(rep, "journal"),),
              _levels(rep, "journal") == ["WARNING"]
              and "turned off" in _detail(rep, "journal"))

        rep = base.Report()
        M.check_journal(rep, tmp, {}, cfgmod, None)
        check("dt13 ...and enabled, it reports rows, files and 'chain intact' - "
              "the verdict comes from the journal's own verify, never from a "
              "second opinion here: %r" % (_detail(rep, "journal"),),
              _levels(rep, "journal") == ["OK"]
              and "1 row(s) in 1 file(s)" in _detail(rep, "journal")
              and "chain intact" in _detail(rep, "journal"))

        # ------------------------------------------ _journal_never_committed
        jdir = _journal_io.journal_dir(tmp)
        have_git = bool(shutil.which("git"))
        if not have_git:
            print("SKIP git-dependent cases (git is not on PATH)")
        else:
            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for k, v in (("user.email", "p@example.com"), ("user.name", "P")):
                subprocess.run(["git", "-C", tmp, "config", k, v], check=True)

            for f in _journal_io.journal_files(jdir):
                _age(f, 3.0)
            check("dt14 an uncommitted journal file YOUNGER than 7 days says "
                  "nothing: that is the normal write-then-commit rhythm, and a "
                  "warning here would fire on every session: %r"
                  % (M._journal_never_committed(_journal_io, jdir),),
                  M._journal_never_committed(_journal_io, jdir) is None)

            for f in _journal_io.journal_files(jdir):
                _age(f, 12.0)
            stale = M._journal_never_committed(_journal_io, jdir)
            check("dt15 ...and one OLDER than 7 days returns (count, age, name) "
                  "- age by MTIME, and the name is the journal-relative path so "
                  "a live and an archived month cannot read as one another: %r"
                  % (stale,),
                  stale is not None and stale[0] == 1 and stale[1] >= 12
                  and stale[2].endswith(".jsonl"))

            rep = base.Report()
            M.check_journal(rep, tmp, {}, cfgmod, tmp)
            check("dt16 ...and check_journal turns that into a WARNING, never a "
                  "FINDING: a finding is positive evidence of forgery, and an "
                  "absent commit is evidence of nothing but absence: %r"
                  % (_detail(rep, "journal"),),
                  "WARNING" in _levels(rep, "journal")
                  and "FINDING" not in _levels(rep, "journal")
                  and "never been committed" in _detail(rep, "journal"))

            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "j"], check=True,
                           stdout=subprocess.DEVNULL)
            check("dt17 committing it retires the answer entirely - the check "
                  "reads git's porcelain, not the filename's month, so a "
                  "committed file of the same age says nothing: %r"
                  % (M._journal_never_committed(_journal_io, jdir),),
                  M._journal_never_committed(_journal_io, jdir) is None)

            first = sorted(_journal_io.journal_files(jdir))[0]
            with open(first, "r", encoding="utf-8") as fh:
                rows = [ln for ln in fh.read().splitlines() if ln.strip()]
            row = json.loads(rows[0])
            row["actor"] = "someone-else"
            with open(first, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "t"], check=True,
                           stdout=subprocess.DEVNULL)
            rep = base.Report()
            M.check_journal(rep, tmp, {}, cfgmod, tmp)
            check("dt18 a row rewritten under the hash that signed it IS a "
                  "FINDING - the chain is append-only and a broken one means a "
                  "row was edited, deleted or reordered, which does not happen "
                  "by accident: %r" % (_detail(rep, "journal"),),
                  _levels(rep, "journal") == ["FINDING"]
                  and "the chain does not hold" in _detail(rep, "journal"))

        check("dt19 an unreadable directory is None rather than a warning - an "
              "unanswerable question is not an accusation: %r"
              % (M._journal_never_committed(_journal_io, None),),
              M._journal_never_committed(_journal_io, None) is None
              and M._journal_never_committed(_journal_io,
                                             os.path.join(tmp, "nope")) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_trail.py --selftest\n")
    raise SystemExit(2)
