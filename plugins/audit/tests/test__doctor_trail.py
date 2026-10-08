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
import re
import shlex
import shutil
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_trail as M                          # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)
import _journal_io                                 # noqa: E402
import _evidence_io                                # noqa: E402
import _panel_composition                          # noqa: E402
import _loader                                     # noqa: E402
import _output                                     # noqa: E402  (the anchor: PLUGIN_ROOT, plugin_version)


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _fix(rep, name):
    return " ".join(r["fix"] or "" for r in rep.rows if r["check"] == name)


def _age(path, days):
    when = time.time() - days * 86400
    os.utime(path, (when, when))


def _committed_journal(root):
    """A git repo at `root` holding two COMMITTED journal rows; returns the
    file they landed in.

    Shared by the two anchor cases below, which are the same setup up to their
    last write: a splice re-chains the rows, a re-spelling rewrites the bytes
    and moves no row. The commit is not scaffolding - `_git_anchor_finding`
    fails open on an untracked file, so a journal git has never seen produces
    no warning to classify at all."""
    os.makedirs(os.path.join(root, "docs", "audit"))
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for k, v in (("user.email", "p@example.com"), ("user.name", "P")):
        subprocess.run(["git", "-C", root, "config", k, v], check=True)
    for tid in ("P1.1", "P1.2"):
        _journal_io.append(root, {"action": "task.complete", "actor": "probe",
                                  "ts": "2026-01-01T00:00:00Z",
                                  "details": {"taskId": tid}})
    subprocess.run(["git", "-C", root, "add", "-A"], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", root, "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "j"], check=True,
                   stdout=subprocess.DEVNULL)
    return sorted(_journal_io.journal_files(_journal_io.journal_dir(root)))[0]


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
              "yet' and NAMES where it would live. It used to say '<path> "
              "exists but holds no rows', asserting the existence of a directory "
              "nothing ever made: %r" % (_detail(rep, "usage ledger"),),
              "no ledger yet" in _detail(rep, "usage ledger")
              and os.path.join(tmp, ".claude", "usage")
              in _detail(rep, "usage ledger"))
        check("dt7 ...and never uses the word 'exists' about it, which is the "
              "half a presence assertion would miss",
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

        # ------------------------------- which WARNING class, and its fix -------
        # THE PAIR IS THE POINT. A re-linked file was made a warning instead of
        # a finding, and the fix text stayed the single sentence about
        # out-of-band drift - so the highest-stakes new class told an operator
        # to look for a git checkout that does not exist. dt43 fails when the
        # classifier never fires (the original defect); dt44 fails when it fires
        # unconditionally, which is the other wrong implementation and the one
        # that looks vacuous. Both fixtures are REAL: a spliced-and-re-chained
        # committed file, and a recorded document edited behind the journal's
        # back.
        #
        # AND THE SAME PAIR AGAIN ONE LEVEL DOWN. `_anchor_warning` says
        # two different things and both open with the same clause, so `relink`
        # keyed on that clause answered for a file where NO row moved and none
        # arrived - the same misclassification, reintroduced by the repair. dt46 is the
        # never-fires direction for the re-spelling; dt43's closing clause is
        # the over-fire direction, and either goes red if the prose that carries
        # a class moves, which is the price of classifying on text at all.
        if not have_git:
            print("SKIP dt43 (git is not on PATH)")
            print("SKIP dt46 (git is not on PATH)")
        else:
            splice = os.path.join(tmp, "relinked")
            sfile = _committed_journal(splice)
            srows, _storn = _journal_io.read_file(sfile)
            forged = dict(srows[0])
            forged["details"] = {"taskId": "P9.9"}
            forged["summary"] = "a row nobody wrote"
            srows.insert(1, forged)
            chained, _moved = _journal_io._rechain(
                srows, os.path.basename(sfile))
            with open(sfile, "w", encoding="utf-8") as fh:
                fh.write(_journal_io.merge_text(chained))
            sres = _journal_io.verify(splice)
            rep = base.Report()
            M.check_journal(rep, splice, {}, cfgmod, splice)
            check("dt43 a fabricated row spliced BETWEEN committed rows and the "
                  "file re-chained is the `relink` class, and its fix says the "
                  "check cannot tell a merge from a splice - never the "
                  "out-of-band-drift sentence, which would send the operator "
                  "looking for a checkout that never happened, and never the "
                  "re-spelling one, which would deny rows arrived: %r / %r"
                  % (_detail(rep, "journal"), _fix(rep, "journal")),
                  _levels(rep, "journal") == ["WARNING"]
                  and M.journal_warning_advice(
                      sres["warnings"])["kinds"] == ["relink"]
                  and "RE-LINKED chain" in _fix(rep, "journal")
                  and "NOTHING HERE CAN TELL THOSE APART" in _fix(rep,
                                                                  "journal")
                  and "out-of-band drift is a document" not in _fix(rep,
                                                                    "journal")
                  and "RE-SPELLED" not in _fix(rep, "journal"))

            # THE FIXTURE IS THE WHOLE CASE. Every row is re-emitted with the
            # SAME content in the SAME order and a legal but non-canonical
            # spelling - spaces after the JSON separators, which `canonical()`
            # never writes. That is the shape a writer outside this plugin
            # leaves: the bytes differ from the committed copy while
            # `anchor_verdict` finds nothing diverged and nothing extra. A
            # fixture that changed a row would have produced the splice
            # warning instead and could not tell the two classes apart.
            respelled = os.path.join(tmp, "respelled")
            rfile = _committed_journal(respelled)
            rrows, _rtorn = _journal_io.read_file(rfile)
            with open(rfile, "w", encoding="utf-8") as fh:
                for row in rrows:
                    fh.write(json.dumps(row, ensure_ascii=False,
                                        separators=(", ", ": ")) + "\n")
            rres = _journal_io.verify(respelled)
            rep = base.Report()
            M.check_journal(rep, respelled, {}, cfgmod, respelled)
            check("dt46 ...while a committed copy merely RE-SPELLED - same "
                  "rows, same order, other bytes - is its own class and must "
                  "NOT draw the re-link advice, which tells the operator to go "
                  "and read rows that do not exist. This is the same defect one "
                  "level up, and it survived because both warnings open with "
                  "the same clause: %r / %r"
                  % (_detail(rep, "journal"), _fix(rep, "journal")),
                  _levels(rep, "journal") == ["WARNING"]
                  and len(rres["warnings"]) == 1
                  and M.journal_warning_advice(
                      rres["warnings"])["kinds"] == ["respelled"]
                  and "RE-SPELLED file" in _fix(rep, "journal")
                  and "RE-LINKED chain" not in _fix(rep, "journal")
                  and "Read the extra rows yourself" not in _fix(rep, "journal")
                  and "out-of-band drift is a document" not in _fix(rep,
                                                                    "journal"))

        # A JOURNAL THAT IS NOT THERE IS NOT A JOURNAL THAT WAS NEVER WRITTEN,
        # and dt11 above is why these two need telling apart: both leave the
        # directory absent, and this check reported both as the ok line "no
        # writes recorded yet". `verify` asks git what the index still holds
        # under the path before it gives up on a walk with nothing to walk, so
        # the removed one arrives here with findings - and a FINDING is right,
        # because a committed trail does not leave by accident.
        if not have_git:
            print("SKIP dt50 (git is not on PATH)")
            print("SKIP dt51 (git is not on PATH)")
        else:
            wiped = os.path.join(tmp, "wiped")
            wfile = _committed_journal(wiped)
            shutil.rmtree(_journal_io.journal_dir(wiped))
            rep = base.Report()
            M.check_journal(rep, wiped, {}, cfgmod, wiped)
            check("dt50 a committed journal directory REMOVED WHOLE is a FINDING "
                  "naming the file git still tracks, not the ok line a project "
                  "that has never recorded anything gets - the chain grades rows "
                  "inside a file and the anchor grades one file, so a file that "
                  "is gone was in neither question: %r / %r"
                  % (_detail(rep, "journal"), _fix(rep, "journal")),
                  _levels(rep, "journal") == ["FINDING"]
                  and os.path.basename(wfile) in _detail(rep, "journal")
                  and "still tracks" in _detail(rep, "journal")
                  and "git checkout --" in _fix(rep, "journal"))
            # THE OVER-FIRE DIRECTION, and the one that decides whether this
            # check survives contact with a fresh clone: restoring the files
            # must take the finding away completely, not soften it.
            subprocess.run(["git", "-C", wiped, "checkout", "--", "."],
                           check=True, stdout=subprocess.DEVNULL)
            rep = base.Report()
            M.check_journal(rep, wiped, {}, cfgmod, wiped)
            check("dt51 SECOND DIRECTION: the same repository with the files put "
                  "back is an OK line again - the finding is bound to what git "
                  "says the worktree is missing, so it cannot linger once "
                  "nothing is: %r" % (_detail(rep, "journal"),),
                  _levels(rep, "journal") == ["OK"]
                  and "chain intact" in _detail(rep, "journal"))

        # ------------------------------------- what the chain was checked AGAINST
        # THE ANCHOR'S THIRD ANSWER, WHICH THIS SURFACE COULD NOT SAY. `verify`
        # has answered per file for a release - compared, or could not ask - and
        # only `audit-journal.py verify` rendered the second, so an operator who
        # opened the doctor instead read "chain intact" over files nothing pins
        # and saw exactly what they saw before the anchor learnt to speak.
        #
        # TWO QUESTIONS, TWO ROWS, and that is what the pair below is for: the
        # chain still holds in dt52 - the warning is not about the rows - while
        # the thing that would have caught a forgery was never asked. dt53 is the
        # over-fire direction and the one that decides whether this row survives
        # a healthy repository: committed files must take it back to OK, or a row
        # that fires on every project is a row somebody switches off.
        if not have_git:
            print("SKIP dt52 (git is not on PATH)")
            print("SKIP dt53 (git is not on PATH)")
        else:
            anch = os.path.join(tmp, "unanchored-trail")
            os.makedirs(os.path.join(anch, "docs", "audit"))
            subprocess.run(["git", "init", "-q", anch], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _k, _v in (("user.email", "p@example.com"), ("user.name", "P")):
                subprocess.run(["git", "-C", anch, "config", _k, _v], check=True)
            _journal_io.append(anch, {"action": "task.complete",
                                      "actor": "probe",
                                      "ts": "2026-01-01T00:00:00Z",
                                      "details": {"taskId": "P1.1"}})
            ares = _journal_io.verify(anch)
            afile = os.path.basename(
                sorted(_journal_io.journal_files(
                    _journal_io.journal_dir(anch)))[0])
            rep = base.Report()
            M.check_journal(rep, anch, {}, cfgmod, anch)
            check("dt52 a journal file git has never seen is a WARNING on its "
                  "OWN row, naming the file and the reason - while the chain "
                  "row still says intact, because the rows really do hold and "
                  "what is missing is the thing they were checked against: "
                  "%r / %r" % (_levels(rep, M.ANCHOR_CHECK),
                               _detail(rep, M.ANCHOR_CHECK)),
                  _levels(rep, M.ANCHOR_CHECK) == ["WARNING"]
                  and len(ares["unanchored"]) == 1
                  and afile in _detail(rep, M.ANCHOR_CHECK)
                  and "no committed copy pins" in _detail(rep, M.ANCHOR_CHECK)
                  and "does not track" in _detail(rep, M.ANCHOR_CHECK)
                  and _levels(rep, "journal") == ["OK"]
                  and "chain intact" in _detail(rep, "journal"))
            check("dt52b ...and it never fails the run. A finding exits this "
                  "command non-zero, and an unestablished basis is not evidence "
                  "that anything is wrong - a repository whose journal is not "
                  "committed yet would fail a build having asked nothing and "
                  "found nothing: %r" % (rep.counts(),),
                  rep.exit_code() == 0
                  and "FINDING" not in _levels(rep, M.ANCHOR_CHECK)
                  and "nothing was found here" in _fix(rep, M.ANCHOR_CHECK))

            subprocess.run(["git", "-C", anch, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", anch, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "j"], check=True,
                           stdout=subprocess.DEVNULL)
            bres = _journal_io.verify(anch)
            rep = base.Report()
            M.check_journal(rep, anch, {}, cfgmod, anch)
            check("dt53 THE OVER-FIRE CASE: committing the same file takes the "
                  "row to OK and says what WAS compared. A row widened until it "
                  "reports a trail every file of which the anchor really did "
                  "ask about passes dt52 and fails here, and it is the one that "
                  "would fire on every healthy project: %r"
                  % (_detail(rep, M.ANCHOR_CHECK),),
                  _levels(rep, M.ANCHOR_CHECK) == ["OK"]
                  and bres["unanchored"] == []
                  and "1 journal file(s) were compared" in _detail(
                      rep, M.ANCHOR_CHECK))

        # A DIRECTORY WITH NOTHING IN IT WAS NOT ASKED ABOUT AND WAS NOT
        # UNASKED: nothing was walked, so a row either way would be a claim
        # about files that are not there. This is the branch that separates
        # "every file was anchored" from "there were no files".
        bare = os.path.join(tmp, "bare-journal")
        os.makedirs(os.path.join(bare, "docs", "audit"))
        os.makedirs(_journal_io.journal_dir(bare))
        rep = base.Report()
        M.check_journal(rep, bare, {}, cfgmod, None)
        check("dt54 a journal directory holding no files draws no anchor row at "
              "all - an OK line there would report an anchor holding over "
              "nothing, which reads as the strongest answer and is the emptiest: "
              "%r" % (_levels(rep, M.ANCHOR_CHECK),),
              _levels(rep, M.ANCHOR_CHECK) == []
              and _levels(rep, "journal") == ["OK"])

        drift = os.path.join(tmp, "drifted")
        os.makedirs(os.path.join(drift, "docs", "audit"))
        dman = os.path.join(drift, mrel)
        with open(dman, "w", encoding="utf-8") as fh:
            fh.write('{"meta": {"v": 1}}\n')
        _journal_io.append(drift, {"action": "composition.write",
                                   "actor": "probe", "target": mrel,
                                   "ts": "2026-01-01T00:00:00Z"})
        with open(dman, "w", encoding="utf-8") as fh:
            fh.write('{"meta": {"v": 2}}\n')
        dres = _journal_io.verify(drift)
        rep = base.Report()
        M.check_journal(rep, drift, {}, cfgmod, None)
        check("dt44 ...and a recorded document edited with no row to explain it "
              "STILL gets the out-of-band-drift sentence and none of the "
              "re-link text. THE OVER-FIRE CASE: a classifier that answered "
              "`relink` for every warning would pass dt43 and fail here: %r"
              % (_fix(rep, "journal"),),
              _levels(rep, "journal") == ["WARNING"]
              and M.journal_warning_advice(dres["warnings"])["kinds"] == ["drift"]
              and "out-of-band drift is a document" in _fix(rep, "journal")
              and "RE-LINKED" not in _fix(rep, "journal"))

        unknown = M.journal_warning_advice(["a class this table never heard of"])
        check("dt45 ...and a warning in NO class gets a pointer and no cause. "
              "Falling back to the drift sentence is how the wrong cause got "
              "printed in the first place, so an unrecognised warning must not "
              "borrow one: %r" % (unknown,),
              unknown["kinds"] == []
              and "no repair text" in unknown["fix"]
              and "out-of-band drift is a document" not in unknown["fix"]
              and "RE-LINKED" not in unknown["fix"])

        # A REAL TORN TAIL, because the table claimed every class it holds goes
        # red when its sentence is reworded and this one had no case at all:
        # rewording `verify`'s partial-line warning left the whole
        # suite green while the class silently lost its advice. dt47 also
        # carries the second direction of dt48's pointer - a list where every
        # warning IS recognised must not draw one, which is the wrong
        # implementation that emits the pointer unconditionally.
        torn = os.path.join(tmp, "torntail")
        os.makedirs(os.path.join(torn, "docs", "audit"))
        _journal_io.append(torn, {"action": "task.complete", "actor": "probe",
                                  "ts": "2026-01-01T00:00:00Z",
                                  "details": {"taskId": "P1.1"}})
        tfile = sorted(_journal_io.journal_files(
            _journal_io.journal_dir(torn)))[0]
        with open(tfile, "a", encoding="utf-8") as fh:
            fh.write('{"action":"task.complete","act')
        tres = _journal_io.verify(torn)
        rep = base.Report()
        M.check_journal(rep, torn, {}, cfgmod, None)
        check("dt47 a file whose last line is half-written is the `torn` class "
              "and gets the interrupted-writer sentence - and NOT the pointer, "
              "which is what an advice list that always appends one would add: "
              "%r / %r" % (_detail(rep, "journal"), _fix(rep, "journal")),
              _levels(rep, "journal") == ["WARNING"]
              and not tres["findings"]
              and M.journal_warning_advice(tres["warnings"])["kinds"] == ["torn"]
              and "a torn tail is an interrupted writer" in _fix(rep, "journal")
              and "no repair text" not in _fix(rep, "journal"))

        # dt48's fixture is real, rather than two hand-written strings:
        # the same basename living AND archived is a class `verify` emits with
        # no row in the table, standing beside a drift warning that has one.
        # The bug dropped the unrecognised half entirely whenever anything else
        # matched, so `/audit:doctor` printed a cause for one warning and
        # nothing at all for the other.
        both = os.path.join(tmp, "dup-and-drift")
        os.makedirs(os.path.join(both, "docs", "audit"))
        bman = os.path.join(both, mrel)
        with open(bman, "w", encoding="utf-8") as fh:
            fh.write('{"meta": {"v": 1}}\n')
        _journal_io.append(both, {"action": "composition.write",
                                  "actor": "probe", "target": mrel,
                                  "ts": "2026-01-01T00:00:00Z"})
        with open(bman, "w", encoding="utf-8") as fh:
            fh.write('{"meta": {"v": 2}}\n')
        bdir = _journal_io.journal_dir(both)
        blive = sorted(_journal_io.journal_files(bdir))[0]
        barch = os.path.join(bdir, _journal_io.ARCHIVE_DIRNAME)
        os.makedirs(barch)
        shutil.copy2(blive, os.path.join(barch, os.path.basename(blive)))
        bres = _journal_io.verify(both)
        badv = M.journal_warning_advice(bres["warnings"])
        rep = base.Report()
        M.check_journal(rep, both, {}, cfgmod, None)
        check("dt48 an unrecognised warning standing BESIDE a recognised one "
              "still gets the pointer, and the recognised one keeps its cause. "
              "Emitting the pointer only when nothing matched passes dt45 and "
              "fails here, which is why dt45 alone left the defect in: %r"
              % (_fix(rep, "journal"),),
              _levels(rep, "journal") == ["WARNING"]
              and len(bres["warnings"]) == 2
              and badv["kinds"] == ["drift"]
              and "out-of-band drift is a document" in _fix(rep, "journal")
              and "no repair text" in _fix(rep, "journal"))

        # WHY THE POINTER HAS TO BE PER WARNING and not per list, on the same
        # fixture: the detail line spends a fixed budget on the warning text
        # (`_output.some_of`) and elides the rest, so the fix is the only place
        # an elided warning is represented at all. The budget is deliberately
        # NOT widened for this - `some_of` is shared, it says how many it left
        # out, and the repair that closes the gap is the one above.
        shown = _detail(rep, "journal")
        elided = [w for w in bres["warnings"] if w not in shown]
        check("dt49 ...and on this fixture the detail line really does elide a "
              "warning, so a class dropped from the fix would leave that "
              "warning with no representation anywhere in the row: %r elided, "
              "detail %r" % (len(elided), shown),
              len(elided) == 1
              and "more" in shown
              and len(badv["fix"].split("; also: ")) == 2)

        # ...AND BEING REPRESENTED IS NOT BEING READABLE, which is what dt49
        # leaves open and this closes. The fix said "no repair text for that
        # warning" and named none, over a detail line that elides on the same
        # fixture - so on any run where the budget reached it, the row told the
        # operator that something they could not see had no explanation. The
        # warning nothing recognised is the one worth the room: a recognised
        # class is one somebody has already thought about.
        #
        # THE UNRECOGNISED SET IS DERIVED FROM THE TABLE rather than named here,
        # so a class added to it moves this case with it instead of leaving it
        # asserting about a warning that now has advice.
        unrec = [w for w in bres["warnings"]
                 if not any(frag in w for _k, frags, _a
                            in M._JOURNAL_WARNING_CLASSES for frag in frags)]
        check("dt49b ...and every warning the table does not recognise is "
              "QUOTED beside its pointer, so the one thing this check cannot "
              "explain still reaches the operator. A pointer about a warning "
              "printed nowhere is a row saying something is wrong and refusing "
              "to say what: %r" % (unrec,),
              len(unrec) == 1
              and all(w in _fix(rep, "journal") for w in unrec)
              and "no repair text" in _fix(rep, "journal"))

        # ------------------------------------------- check_running_plugin -------
        # THREE OUTCOMES, and the third is the one this file exists to keep
        # honest: they agree, they differ, or the running copy could not be
        # determined - and the last is not the first. Every fixture below is a
        # state directory, because a state directory is the only channel there
        # is: `/audit:doctor` is a different process from a hook and the harness
        # substitutes ${CLAUDE_PLUGIN_ROOT} into a command string instead of
        # exporting it, so there is no environment variable here to read.
        gbw = _loader.load(os.path.join(_harness.HOOKS_DIR,
                                        "guard-bash-writes.py"),
                           modname="dt_guard_bash_writes")
        shape = M.bash_state_shape(gbw)
        here = {"root": _output.PLUGIN_ROOT,
                "version": _output.plugin_version()}
        elsewhere = {"root": os.path.join(tmp, "cached-copy"),
                     "version": "0.43.0"}

        check("dt20 `bash_state_shape` reads every field off the guard's own "
              "module - the key set from `default_state()`, both name prefixes "
              "from its templates - so a key added there moves this with it: %r"
              % (shape,),
              shape["keys"] == sorted(gbw.default_state().keys())
              and shape["prefix"] == gbw.STATE_FILE.split("%s")[0]
              and shape["sidecar"] == gbw.PLUGIN_SIDECAR.split("%s")[0])
        check("dt21 ...and the sidecar prefix STARTS WITH the session prefix, "
              "which is why the drift walk has to test it first. If it did not, "
              "this pin would be asserting nothing about the order: %r"
              % (shape["sidecar"],),
              shape["sidecar"].startswith(shape["prefix"])
              and shape["sidecar"] != shape["prefix"])

        check("dt22 `_same_copy` needs root AND version. A version replaced "
              "under one root is an in-place upgrade and one version under two "
              "roots is a checkout beside an installation - either alone reads "
              "one of those wrong",
              M._same_copy(here, dict(here)) is True
              and M._same_copy(here, dict(here, version="9.9.9")) is False
              and M._same_copy(here, dict(here, root=tmp)) is False)
        check("dt23 ...and a record naming NO root is equal to nothing, not "
              "even to another rootless one - `os.path.realpath('')` is the "
              "working directory, so an unguarded comparison would make two "
              "empty stamps agree",
              M._same_copy({"root": "", "version": "1.0.0"},
                           {"root": "", "version": "1.0.0"}) is False)

        # -- the pure verdict, all four ways
        v = M.running_plugin_verdict(here, [dict(here, session="a", mtime=1)],
                                     [], [])
        check("dt24 a stamp naming this copy, and nothing else, is the only "
              "shape that may read as agreement: %r" % (v["verdict"],),
              v["verdict"] == "match" and v["basis"] == ["stamp"])
        v = M.running_plugin_verdict(here, [], [], [])
        check("dt25 an EMPTY state directory is `unestablished` with no basis - "
              "not `match`. This is the case the whole item is about: a check "
              "that cleared nothing must not read as clean: %r" % (v,),
              v["verdict"] == "unestablished" and v["basis"] == [])
        fresh = time.time()
        v = M.running_plugin_verdict(
            here, [dict(elsewhere, session="old", mtime=fresh)], [], [])
        check("dt26 a stamp naming another copy is `differ`, on the stamp: %r"
              % (v,),
              v["verdict"] == "differ" and v["basis"] == ["stamp"]
              and len(v["others"]) == 1)
        v = M.running_plugin_verdict(
            here, [], [{"file": "bash-writes-x.json",
                        "missing": ["bgLaunches"], "extra": []}], [])
        check("dt27 ...and a state file's SHAPE alone is `differ` too, on the "
              "state shape. This is the arm that works against a copy too old "
              "to have ever stamped anything - the evidence the incident was "
              "actually diagnosed by: %r" % (v,),
              v["verdict"] == "differ" and v["basis"] == ["state shape"])
        v = M.running_plugin_verdict(
            here, [dict(here, session="new", mtime=2)],
            [{"file": "bash-writes-old.json", "missing": ["bgLaunches"],
              "extra": []}], [])
        check("dt28 drift OUTRANKS a stamp that agrees, rather than being "
              "hidden behind it: two sessions in one checkout can run two "
              "copies, so one session vouching for itself says nothing about "
              "the one beside it: %r" % (v["basis"],),
              v["verdict"] == "differ" and v["basis"] == ["state shape"])
        v = M.running_plugin_verdict(here, [dict(here, session="a", mtime=1)],
                                     [], ["running-plugin-torn.json"])
        check("dt29 a stamp that could not be READ blocks agreement - it is a "
              "session whose copy this command could not name, so 'every stamp "
              "names this one' has stopped being true of what is on disk: %r"
              % (v["verdict"],), v["verdict"] == "unestablished")
        v = M.running_plugin_verdict(
            here, [dict(elsewhere, session="old", mtime=fresh)], [],
            ["running-plugin-torn.json"])
        check("dt30 ...but it does NOT block refutation. The asymmetry is the "
              "point: a copy already named by another stamp stays named "
              "whatever the unreadable one said: %r" % (v["verdict"],),
              v["verdict"] == "differ")

        # -- the shape walk, against real files
        rp = os.path.join(tmp, "rp-state")
        os.makedirs(rp)

        def _slot(name, obj):
            with open(os.path.join(rp, name), "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        _slot(gbw.STATE_FILE % "current", gbw.default_state())
        check("dt31 a slot this copy itself wrote produces NO drift. THE "
              "OVER-FIRE ARM: it passes on the unfixed code by construction and "
              "is the only case that fails when the comparison is loosened into "
              "always reporting a mismatch: %r"
              % (M.state_shape_drift(rp, shape),),
              M.state_shape_drift(rp, shape) == [])
        aged = dict(gbw.default_state())
        aged.pop("bgLaunches")
        _slot(gbw.STATE_FILE % "aged", aged)
        drift = M.state_shape_drift(rp, shape)
        check("dt32 a slot missing a key this copy writes is drift, and the "
              "KEY is named - the whole diagnosis is which release the writer "
              "predates: %r" % (drift,),
              len(drift) == 1 and drift[0]["missing"] == ["bgLaunches"]
              and drift[0]["extra"] == [])
        _slot(gbw.PLUGIN_SIDECAR % "somebody", {"pluginWrote": ["a"]})
        check("dt33 ...while a plugin SIDECAR is skipped. It shares the session "
              "prefix and holds one unrelated key, so counting it would report "
              "drift on every project that has ever journalled a write: %r"
              % (M.state_shape_drift(rp, shape),),
              len(M.state_shape_drift(rp, shape)) == 1)
        ahead = dict(gbw.default_state())
        ahead["somethingNewer"] = []
        _slot(gbw.STATE_FILE % "ahead", ahead)
        extra = [d for d in M.state_shape_drift(rp, shape)
                 if d["file"] == gbw.STATE_FILE % "ahead"]
        check("dt34 a slot carrying a key this copy does NOT write is reported "
              "as `extra`, not as `missing` - a newer writer and an older one "
              "are different diagnoses: %r" % (extra,),
              len(extra) == 1 and extra[0]["extra"] == ["somethingNewer"]
              and extra[0]["missing"] == [])

        # -- the rendered row, driven through the real check
        state = os.path.join(tmp, "rp-proj", ".claude", "state")
        os.makedirs(state)
        proj = os.path.join(tmp, "rp-proj")
        rep = base.Report()
        M.check_running_plugin(rep, proj, {}, cfgmod)
        check("dt35 with nothing on disk the row is a WARNING that says NOT "
              "ESTABLISHED and names the copy this command is running from - "
              "the half that is always knowable: %r"
              % (_detail(rep, "running plugin"),),
              _levels(rep, "running plugin") == ["WARNING"]
              and "NOT ESTABLISHED" in _detail(rep, "running plugin")
              and _output.PLUGIN_ROOT in _detail(rep, "running plugin"))
        check("dt36 ...and it never says they agree. The word is the defect: "
              "the row this replaced answered about the installation while a "
              "guard several releases behind was in force",
              "agreeing" not in _detail(rep, "running plugin").split(
                  "is not the same as")[0])

        with open(os.path.join(state, cfgmod.RUNNING_STAMP % "sess-1"), "w",
                  encoding="utf-8") as fh:
            json.dump({"root": _output.PLUGIN_ROOT,
                       "version": _output.plugin_version()}, fh)
        rep = base.Report()
        M.check_running_plugin(rep, proj, {}, cfgmod)
        check("dt37 a stamp from this very copy turns the row OK. THE OVER-FIRE "
              "ARM for the whole check: it is the case that fails when the "
              "comparison is broken into always reporting a mismatch: %r"
              % (_detail(rep, "running plugin"),),
              _levels(rep, "running plugin") == ["OK"]
              and "NOT ESTABLISHED" not in _detail(rep, "running plugin"))

        with open(os.path.join(state, cfgmod.RUNNING_STAMP % "sess-2"), "w",
                  encoding="utf-8") as fh:
            json.dump({"root": os.path.join(tmp, "cached-copy"),
                       "version": "0.43.0"}, fh)
        rep = base.Report()
        M.check_running_plugin(rep, proj, {}, cfgmod)
        said = _detail(rep, "running plugin")
        check("dt38 a second session running an older copy is a WARNING naming "
              "BOTH sides and the basis, and never a FINDING - a stale plugin "
              "is a thing to tell somebody, not a thing to block on: %r"
              % (said,),
              _levels(rep, "running plugin") == ["WARNING"]
              and "0.43.0" in said and _output.PLUGIN_ROOT in said
              and "basis: stamp" in said)
        check("dt39 ...and the fix names the only thing that actually works, "
              "which is a new session - CLAUDE_PLUGIN_ROOT is the harness's to "
              "set and a running session cannot be made to reload it",
              [r["fix"] for r in rep.rows if r["check"] == "running plugin"
               and "new Claude Code session" in (r["fix"] or "")])

        os.remove(os.path.join(state, cfgmod.RUNNING_STAMP % "sess-2"))
        with open(os.path.join(state, gbw.STATE_FILE % "sess-3"), "w",
                  encoding="utf-8") as fh:
            json.dump(aged, fh)
        rep = base.Report()
        M.check_running_plugin(rep, proj, {}, cfgmod)
        said = _detail(rep, "running plugin")
        check("dt40 a slot written by a copy that predates a key is a WARNING "
              "on the STATE SHAPE even while a stamp agrees, and it names the "
              "missing key: %r" % (said,),
              _levels(rep, "running plugin") == ["WARNING"]
              and "basis: state shape" in said and "bgLaunches" in said)

        os.remove(os.path.join(state, gbw.STATE_FILE % "sess-3"))
        with open(os.path.join(state, cfgmod.RUNNING_STAMP % "sess-4"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        rep = base.Report()
        M.check_running_plugin(rep, proj, {}, cfgmod)
        said = _detail(rep, "running plugin")
        check("dt41 a torn stamp beside a good one drops the row out of OK and "
              "SAYS SO, counting it rather than dropping it - a file that "
              "exists and cannot be read is evidence a copy ran, and silently "
              "skipping it would look identical to nothing ever running: %r"
              % (said,),
              _levels(rep, "running plugin") == ["WARNING"]
              and "could not be read" in said and "NOT ESTABLISHED" in said)
        check("dt42 ...and the row stays advisory throughout: not one of the "
              "branches above produced a FINDING, so `/audit:doctor` still "
              "exits 0 over a plugin that is merely out of date",
              rep.counts()["FINDING"] == 0)

        # -- the newest stamp per copy, and a dead session's stamp as history
        # A session that has ended leaves its stamp behind, and state GC keeps it
        # for days. Counting every stamp that is not this copy as drift held the
        # row yellow on one dead session's file while every newer stamp named the
        # running copy, and "start a new session" could not clear it: the new
        # session stamps beside the dead one, it does not replace it.
        proj2 = os.path.join(tmp, "rp2-proj")
        state2 = os.path.join(proj2, ".claude", "state")
        os.makedirs(state2)

        def _stamp(session, copy, age_s):
            path = os.path.join(state2, cfgmod.RUNNING_STAMP % session)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(copy, fh)
            when = time.time() - age_s
            os.utime(path, (when, when))
            return path

        _stamp("live-cur", here, 60)
        dead = _stamp("6fc1a222-dead", {"root": "/nonexistent/cache/audit/2.3.0",
                                        "version": "2.3.0"}, 6 * 86400)
        rep = base.Report()
        M.check_running_plugin(rep, proj2, {}, cfgmod)
        said = _detail(rep, "running plugin")
        check("rh1 one SIX-DAY-OLD stamp from a dead session naming an older "
              "plugin does not hold the row at WARNING while every newer stamp "
              "names the running copy: it is OK, and the old stamp is reported "
              "as HISTORY - named, aged, with the file to prune: %r" % (said,),
              _levels(rep, "running plugin") == ["OK"]
              and "6fc1a222-dead" in said and "6 days" in said
              and dead in said and "2.3.0" in said)

        # Liveness is a copy's OWN age against a stated idle bound; the stamp of
        # the session asking is never the yardstick, because that session has
        # always just prompted and would make every other session look old.
        bound = M.IDLE_BOUND_SECONDS
        now = 10 * bound
        v = M.running_plugin_verdict(
            here, [dict(here, session="asker", mtime=now - 1),
                   dict(elsewhere, session="busy", mtime=now - 30)], [], [],
            now=now)
        check("rh2 THE REVIEW'S CASE: a foreign stamp 30 s old beside the asking "
              "session's 1 s old is LIVE - a session mid-turn on an older copy is "
              "exactly what the row exists to find - so the verdict is `differ`, "
              "not history: %r" % ((v["verdict"],
                                    [h["session"] for h in v["history"]]),),
              v["verdict"] == "differ" and v["history"] == []
              and [o["session"] for o in v["others"]] == ["busy"])
        v = M.running_plugin_verdict(
            here, [dict(here, session="asker", mtime=now - 1),
                   dict(elsewhere, session="gone", mtime=now - bound - 1)], [], [],
            now=now)
        check("rh3 a foreign copy is history only PAST the idle bound, measured "
              "from now: %r" % ((v["verdict"],
                                 [h["session"] for h in v["history"]]),),
              v["verdict"] == "match" and v["others"] == []
              and [h["session"] for h in v["history"]] == ["gone"])
        v = M.running_plugin_verdict(
            here, [dict(elsewhere, session="edge", mtime=now - bound)], [], [],
            now=now)
        check("rh4 ...and a stamp exactly AT the bound is still live - the bound "
              "is how long a live session may go without a guarded tool call: %r"
              % (v["verdict"],), v["verdict"] == "differ")
        v = M.running_plugin_verdict(
            here, [dict(here, session="asker", mtime=now - 1),
                   dict(elsewhere, session="gone", mtime=now - bound - 1)], [],
            ["running-plugin-torn.json"], now=now)
        check("rh5 ...and history does not rescue a TORN stamp: an unreadable "
              "file is a session this command cannot date or name, so agreement "
              "stays unestablished: %r" % (v["verdict"],),
              v["verdict"] == "unestablished")

        _stamp("live-other", elsewhere, 30)
        rep = base.Report()
        M.check_running_plugin(rep, proj2, {}, cfgmod)
        said = _detail(rep, "running plugin")
        check("rh6 a live foreign stamp is a WARNING that carries its AGE and "
              "says it may still be running - never 'not in force': %r" % (said,),
              _levels(rep, "running plugin") == ["WARNING"]
              and "0.43.0" in said and "second" in said
              and "may still be running" in said and "not in force" not in said)
        check("rh7 ...and the history clause states the idle bound WITH its "
              "number, so a reader can argue with it: %r" % (said,),
              "%d-minute" % (M.IDLE_BOUND_SECONDS // 60,) in said)
        check("rh8 ...and history is worded as what the bound can know - no "
              "guarded tool call inside it, so ENDED OR IDLE waiting on its user - "
              "not as a claim the session is gone: %r" % (said,),
              "ended, or idle waiting on its user" in said)

        proj3 = os.path.join(tmp, "rp3-proj")
        state3 = os.path.join(proj3, ".claude", "state")
        os.makedirs(state3)
        for session, age_s in (("a-older", 300), ("b-younger", 30)):
            path3 = os.path.join(state3, cfgmod.RUNNING_STAMP % session)
            with open(path3, "w", encoding="utf-8") as fh:
                json.dump(elsewhere, fh)
            when3 = time.time() - age_s
            os.utime(path3, (when3, when3))
        rep = base.Report()
        M.check_running_plugin(rep, proj3, {}, cfgmod)
        said3 = _detail(rep, "running plugin")
        check("rh9 two sessions on one foreign copy: 'last active' is the YOUNGER "
              "stamp, whatever order the files sort in - the older session's age "
              "is not the copy's last activity: %r" % (said3,),
              "30 seconds ago" in said3 and "5 minutes ago" not in said3)

        class _NameOrder(object):
            """The hooks config, with its stamp reader returning FILENAME order -
            the order a reader that did not sort by mtime would hand over."""
            def __getattr__(self, name):
                return getattr(cfgmod, name)

            def running_plugin_stamps(self, state_dir):
                read = cfgmod.running_plugin_stamps(state_dir)
                return dict(read, stamps=sorted(read["stamps"],
                                                key=lambda st: st["session"]))
        rep = base.Report()
        M.check_running_plugin(rep, proj3, {}, _NameOrder())
        said4 = _detail(rep, "running plugin")
        check("rh9b ...and that holds when the stamps arrive in filename order: the "
              "row picks the newest stamp per copy itself rather than trusting the "
              "reader's order: %r" % (said4,),
              "30 seconds ago" in said4 and "5 minutes ago" not in said4)

        with open(os.path.join(_harness.HOOKS_DIR, "hooks.json"), "r",
                  encoding="utf-8") as fh:
            wiring = json.load(fh)
        matcher = [m.get("matcher") for m in wiring["hooks"]["PreToolUse"]
                   if any("guard-secrets-read.py" in h.get("command", "")
                          for h in m.get("hooks", []))]
        with open(os.path.join(_output.PLUGIN_ROOT, "commands", "doctor.md"), "r",
                  encoding="utf-8") as fh:
            doc = fh.read()
        check("rh10 doctor.md states the refresh limit as the refreshing hook's "
              "MATCHER, the one hooks.json wires, rather than a partial list of "
              "tools it misses: %r" % (matcher,),
              len(matcher) == 1 and ("`%s`" % (matcher[0],)) in doc
              and "hooks.json" in doc)
        with open(os.path.join(_output.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md"), "r",
                  encoding="utf-8") as fh:
            guide = fh.read()
        para = guide[guide.index("**It grades each copy's own age"):]
        para = para[:para.index("\n\n")]
        check("rh11 ...and the guide's paragraph on the same row states it the same "
              "way, from the same matcher, with no partial list of tools left "
              "beside it - two copies of a limit are one copy and one lie: %r"
              % (para[-300:],),
              len(matcher) == 1 and ("`%s`" % (matcher[0],)) in para
              and "Edit, Write, Glob and agent calls" not in para)
    finally:
        _harness.remove_tree(tmp)

    # --- check_task_restarts / check_gate_patterns: their own fresh project, --
    # --- so none of the sixty-odd cases above can leave a row behind that   --
    # --- this pattern count would silently absorb.                          --
    patt = _harness.fixture_root("doctor-trail-patterns-")
    try:
        os.makedirs(os.path.join(patt, "docs", "audit"))

        rep = base.Report()
        M.check_task_restarts(rep, patt)
        check("dtp1 no `task.start` rows anywhere reads NOT ESTABLISHED, never "
              "a clean OK - a fresh manifest has not earned a claim about "
              "restarts it has no rows to support: %r"
              % (_levels(rep, "task restarts"),),
              _levels(rep, "task restarts") == ["WARNING"]
              and "cannot be established" in _detail(rep, "task restarts"))

        _journal_io.append(patt, {"action": "task.start", "actor": "probe",
                                  "ts": "2026-01-01T00:00:00Z",
                                  "details": {"taskId": "P1.1"}})
        _journal_io.append(patt, {"action": "task.start", "actor": "probe",
                                  "ts": "2026-01-02T00:00:00Z",
                                  "details": {"taskId": "P1.2"}})
        rep = base.Report()
        M.check_task_restarts(rep, patt)
        check("dtp2 ONE OCCURRENCE IS NOT A PATTERN: every task here started "
              "exactly once, so this is a clean OK and not a warning about "
              "restarts nobody had: %r" % (_levels(rep, "task restarts"),),
              _levels(rep, "task restarts") == ["OK"])

        _journal_io.append(patt, {"action": "task.start", "actor": "probe",
                                  "ts": "2026-01-03T00:00:00Z",
                                  "details": {"taskId": "P1.1"}})
        rep = base.Report()
        M.check_task_restarts(rep, patt)
        check("dtp3 a task started past the floor is the pattern this trail "
              "supports, and it names the task: %r" % (_detail(rep,
                                                              "task restarts"),),
              _levels(rep, "task restarts") == ["WARNING"]
              and "P1.1" in _detail(rep, "task restarts"))

        # -------------------------------------------------- check_gate_patterns
        rep = base.Report()
        M.check_gate_patterns(rep, patt, "docs/audit/audit-plan.json")
        check("dtp4 no evidence rows at all reads NOT ESTABLISHED for gate "
              "patterns too, the same taxonomy as the restart check above: %r"
              % (_levels(rep, "gate patterns"),),
              _levels(rep, "gate patterns") == ["WARNING"]
              and "cannot be established" in _detail(rep, "gate patterns"))

        _evidence_io.append_row(patt, {"v": 1, "runId": "g1",
            "ts": "2026-01-01T00:00:00Z", "scope": "task", "status": "passed",
            "steps": [{"name": "lint", "command": "ruff check .", "exit": 0}],
            "failed": []})
        rep = base.Report()
        M.check_gate_patterns(rep, patt, "docs/audit/audit-plan.json")
        check("dtp5 a gate recorded below the floor is neither OK nor a "
              "never-failed finding - it is not established, named as such: "
              "%r" % (_detail(rep, "gate patterns"),),
              _levels(rep, "gate patterns") == ["WARNING"]
              and "below the floor" in _detail(rep, "gate patterns"))

        _evidence_io.append_row(patt, {"v": 1, "runId": "g2",
            "ts": "2026-01-02T00:00:00Z", "scope": "task", "status": "passed",
            "steps": [{"name": "lint", "command": "ruff check .", "exit": 0}],
            "failed": []})
        rep = base.Report()
        M.check_gate_patterns(rep, patt, "docs/audit/audit-plan.json")
        check("dtp6 a gate run past the floor that has never failed is the "
              "pattern a doctor can name that a state never could - a "
              "candidate to stop paying for: %r"
              % (_detail(rep, "gate patterns"),),
              _levels(rep, "gate patterns") == ["WARNING"]
              and "candidate to drop" in _detail(rep, "gate patterns"))

        _evidence_io.append_row(patt, {"v": 1, "runId": "g3",
            "ts": "2026-01-03T00:00:00Z", "scope": "task", "status": "failed",
            "steps": [{"name": "lint", "command": "ruff check .", "exit": 1}],
            "failed": ["lint"]})
        rep = base.Report()
        M.check_gate_patterns(rep, patt, "docs/audit/audit-plan.json")
        check("dtp7 SECOND DIRECTION: the moment that same gate has failed "
              "once, the never-failed claim must stop being made about it - "
              "a check that kept warning here would be the widened, "
              "over-firing half of this pattern: %r"
              % (_levels(rep, "gate patterns"),),
              _levels(rep, "gate patterns") == ["OK"])
    finally:
        shutil.rmtree(patt, ignore_errors=True)

    # --- check_gate_economy: its own fresh project, for the same reason ------
    # `patt` is not reused - fixture rows above already carry a "lint" gate
    # that has failed once, and this block needs full control over which
    # gate name has failed, which is thin, and what each run's durationMs is.
    econ = _harness.fixture_root("doctor-trail-economy-")

    def _step(name, ms=None, exitcode=0):
        step = {"name": name, "command": name, "exit": exitcode}
        if ms is not None:
            step["durationMs"] = ms
        return step

    def _row(run_id, ts, *steps):
        _evidence_io.append_row(econ, {"v": 1, "runId": run_id, "ts": ts,
                                       "scope": "task", "status": "passed",
                                       "steps": list(steps), "failed": []})

    try:
        os.makedirs(os.path.join(econ, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        no_budget = {"meta": {}, "phases": []}

        rep = base.Report()
        M.check_gate_economy(rep, econ, manifest_rel, no_budget)
        check("dge1 no meta.gateBudgetMs at all: an OK row saying so, never "
              "a warning - the budget is opt-in and an unset one is not a "
              "claim that anything costs too much: %r"
              % (_levels(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["OK"]
              and "no budget declared" in _detail(rep, "gate economy")
              and "meta.gateBudgetMs" in _detail(rep, "gate economy"))

        budgeted = {"meta": {"gateBudgetMs": 500}, "phases": []}
        rep = base.Report()
        M.check_gate_economy(rep, econ, manifest_rel, budgeted)
        check("dge2 a budget with no evidence rows at all is NOT ESTABLISHED, "
              "the same taxonomy check_gate_patterns uses for the same "
              "reason - a fresh plan has not earned a claim about cost: %r"
              % (_levels(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["WARNING"]
              and "cannot be" not in _detail(rep, "gate economy")
              and "no evidence rows recorded yet" in _detail(rep, "gate economy"))

        # dge3 (RED-FIRST): past the floor, never failed, mean cost over the
        # budget - the repro this task exists to make FAIL on current code
        # (check_gate_economy did not exist before this change).
        _row("e1", "2026-01-01T00:00:00Z", _step("lint", 600))
        _row("e2", "2026-01-02T00:00:00Z", _step("lint", 600))
        phased = {"meta": {"gateBudgetMs": 500},
                 "phases": [{"id": "P1", "testGate": ["lint"]}]}
        rep = base.Report()
        M.check_gate_economy(rep, econ, manifest_rel, phased)
        check("dge3 past the floor, never failed, mean 600ms over a 500ms "
              "budget: a WARNING naming the entry, its runs and both "
              "numbers: %r" % (_detail(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["WARNING"]
              and "lint" in _detail(rep, "gate economy")
              and "ran 2" in _detail(rep, "gate economy")
              and "600 ms" in _detail(rep, "gate economy")
              and "500 ms" in _detail(rep, "gate economy"))
        check("dge3b the remedy names the phase that carries the entry and "
              "is not signed off, PLUS the new-phase remedy - two different "
              "questions, both answered: %r" % (_fix(rep, "gate economy"),),
              "/audit:phase retarget P1 --gate-drop lint"
                  in _fix(rep, "gate economy")
              and "add it to meta.phaseGate.exclude" in _fix(rep, "gate economy")
              and "meta.phaseGate.always" not in _fix(rep, "gate economy"))

        # dge4: the phase is signed off - retargeting it changes nothing an
        # operator can act on, so it must not be named; the exclude line
        # still is, because a NEW phase is unaffected by any phase's sign-off.
        signed_off = {"meta": {"gateBudgetMs": 500},
                     "phases": [{"id": "P1", "testGate": ["lint"],
                               "review": {"status": "passed"}}]}
        rep = base.Report()
        M.check_gate_economy(rep, econ, manifest_rel, signed_off)
        check("dge4 a signed-off phase draws no retarget remedy, but the "
              "plan-wide exclude line still fires: %r" % (_fix(rep, "gate economy"),),
              "retarget" not in _fix(rep, "gate economy")
              and "add it to meta.phaseGate.exclude" in _fix(rep, "gate economy"))

        # dge5: the entry is ALSO listed in meta.phaseGate.always, which
        # OUTRANKS exclude (phase_gate_default's own rule) - so the exclude
        # line alone would not actually stop it recurring, and the always
        # line must be named too.
        always_listed = {"meta": {"gateBudgetMs": 500,
                                 "phaseGate": {"always": ["lint"]}},
                         "phases": [{"id": "P1", "testGate": ["lint"]}]}
        rep = base.Report()
        M.check_gate_economy(rep, econ, manifest_rel, always_listed)
        check("dge5 listed in meta.phaseGate.always too: the remedy also "
              "says to take it out of there, because always wins over "
              "exclude: %r" % (_fix(rep, "gate economy"),),
              "take it out of meta.phaseGate.always" in _fix(rep, "gate economy"))
    finally:
        shutil.rmtree(econ, ignore_errors=True)

    # --- allow cases, each its own project so one history cannot leak into --
    # --- another's classification. ------------------------------------------
    econ2 = _harness.fixture_root("doctor-trail-economy-failed-")
    try:
        os.makedirs(os.path.join(econ2, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        _evidence_io.append_row(econ2, {"v": 1, "runId": "f1",
            "ts": "2026-01-01T00:00:00Z", "scope": "task", "status": "passed",
            "steps": [{"name": "slow", "command": "slow", "exit": 0,
                      "durationMs": 9000}], "failed": []})
        _evidence_io.append_row(econ2, {"v": 1, "runId": "f2",
            "ts": "2026-01-02T00:00:00Z", "scope": "task", "status": "failed",
            "steps": [{"name": "slow", "command": "slow", "exit": 1,
                      "durationMs": 9000}], "failed": ["slow"]})
        rep = base.Report()
        M.check_gate_economy(rep, econ2, manifest_rel,
                             {"meta": {"gateBudgetMs": 100}, "phases": []})
        check("dge6 ALLOW CASE: an entry that has failed once, however far "
              "over budget, is not named at all - only a gate that never "
              "fails is graded on cost: %r" % (_detail(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["OK"]
              and "slow" not in _detail(rep, "gate economy"))
    finally:
        shutil.rmtree(econ2, ignore_errors=True)

    econ3 = _harness.fixture_root("doctor-trail-economy-total-vs-mean-")
    try:
        os.makedirs(os.path.join(econ3, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        # MUTATION PIN, both directions: three runs at 400ms each - a TOTAL
        # of 1200ms clears the 1000ms budget while the MEAN (400ms) does
        # not. The correct code reads mean, not total, and must stay quiet;
        # a version that compared the total instead would warn here, which
        # is exactly the case that looks vacuous and is not (no-silent-pass:
        # "mutate in both directions").
        for i in range(3):
            _evidence_io.append_row(econ3, {"v": 1, "runId": "t%d" % i,
                "ts": "2026-01-0%dT00:00:00Z" % (i + 1), "scope": "task",
                "status": "passed",
                "steps": [{"name": "steady", "command": "steady", "exit": 0,
                          "durationMs": 400}], "failed": []})
        rep = base.Report()
        M.check_gate_economy(rep, econ3, manifest_rel,
                             {"meta": {"gateBudgetMs": 1000}, "phases": []})
        check("dge7 MUTATION PIN (total vs mean): total 1200ms clears a "
              "1000ms budget, mean 400ms does not - reading the mean must "
              "stay quiet here: %r" % (_levels(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["OK"]
              and "steady" not in _detail(rep, "gate economy"))
    finally:
        shutil.rmtree(econ3, ignore_errors=True)

    econ4 = _harness.fixture_root("doctor-trail-economy-unmeasured-")
    try:
        os.makedirs(os.path.join(econ4, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        for i in range(2):
            _evidence_io.append_row(econ4, {"v": 1, "runId": "u%d" % i,
                "ts": "2026-01-0%dT00:00:00Z" % (i + 1), "scope": "task",
                "status": "passed",
                "steps": [{"name": "silent", "command": "silent",
                          "exit": 0}], "failed": []})
        rep = base.Report()
        M.check_gate_economy(rep, econ4, manifest_rel,
                             {"meta": {"gateBudgetMs": 1000}, "phases": []})
        check("dge8 ALLOW CASE: past the floor, never failed, but no step "
              "ever carried a durationMs - named as UNMEASURED, never as "
              "cheap, and never a warning: %r" % (_detail(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["OK"]
              and "silent" in _detail(rep, "gate economy")
              and _detail(rep, "gate economy").count("unmeasured") == 1)
    finally:
        shutil.rmtree(econ4, ignore_errors=True)

    econ5 = _harness.fixture_root("doctor-trail-economy-mixed-measured-")
    try:
        os.makedirs(os.path.join(econ5, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        # RED-FIRST (this task): two runs that carried a durationMs of 600ms
        # each, beside two that carried none - `gate_tally` counts all four
        # as `ran`, so a mean that divides the measured total by `ran`
        # (1200 / 4 = 300) clears a 500ms budget and hides a gate that is, on
        # every run actually measured, 100ms over it. Dividing by the number
        # of steps that contributed a durationMs (1200 / 2 = 600) must warn.
        for i in range(2):
            _evidence_io.append_row(econ5, {"v": 1, "runId": "m%d" % i,
                "ts": "2026-01-0%dT00:00:00Z" % (i + 1), "scope": "task",
                "status": "passed",
                "steps": [{"name": "lint", "command": "lint", "exit": 0,
                          "durationMs": 600}], "failed": []})
        for i in range(2):
            _evidence_io.append_row(econ5, {"v": 1, "runId": "n%d" % i,
                "ts": "2026-01-0%dT00:00:00Z" % (i + 3), "scope": "task",
                "status": "passed",
                "steps": [{"name": "lint", "command": "lint", "exit": 0}],
                "failed": []})
        rep = base.Report()
        M.check_gate_economy(rep, econ5, manifest_rel,
                             {"meta": {"gateBudgetMs": 500}, "phases": []})
        check("dge9 a history mixing measured and unmeasured runs must not "
              "dilute the mean toward the unmeasured runs - the mean is "
              "taken over the runs that carried a durationMs (600ms), over "
              "the 500ms budget, and must warn: %r"
              % (_detail(rep, "gate economy"),),
              _levels(rep, "gate economy") == ["WARNING"]
              and "lint" in _detail(rep, "gate economy")
              and "600 ms" in _detail(rep, "gate economy")
              and "500 ms" in _detail(rep, "gate economy"))
    finally:
        shutil.rmtree(econ5, ignore_errors=True)

    # --- check_shadow_recall: its own fresh project --------------------------
    recall = _harness.fixture_root("doctor-trail-shadow-recall-")

    def _shadow_row(project, run_id, ts, listed, full, missed=None):
        """One evidence row through `_evidence_io.row_for` - THE WRITER'S OWN
        SHAPE, not a hand-built dict, per this task's instruction that these
        fixtures ride the same function `run-test-gate.py` calls."""
        result = {"status": "failed", "durationMs": 900,
                  "failed": missed or [], "ranTotal": full,
                  "coverageBasis": None, "treeBasis": "b", "treeMutated": [],
                  "overlap": None, "steps": [],
                  "shadow": {"listed": listed, "full": full,
                            "missed": missed or []}}
        ident = {"runId": run_id, "ts": ts, "attempt": 1, "via": "cli"}
        row = _evidence_io.row_for(project, result, "phase", {"phaseId": "P1"},
                                   ident, published=[])
        _evidence_io.append_row(project, row)
        return row

    def _plain_row(project, run_id, ts):
        """A recorded run that computed NO derived gate at all - the allow
        case `check_shadow_recall` must contribute nothing for."""
        result = {"status": "passed", "durationMs": 100, "failed": [],
                  "ranTotal": 1, "coverageBasis": None, "treeBasis": "b",
                  "treeMutated": [], "overlap": None, "steps": []}
        ident = {"runId": run_id, "ts": ts, "attempt": 1, "via": "cli"}
        row = _evidence_io.row_for(project, result, "phase", {"phaseId": "P1"},
                                   ident, published=[])
        _evidence_io.append_row(project, row)
        return row

    try:
        os.makedirs(os.path.join(recall, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"

        rep = base.Report()
        M.check_shadow_recall(rep, recall, manifest_rel,
                              {"meta": {}, "phases": []})
        check("dsr1 no meta.phaseGate.mode at all: an OK row saying no "
              "derivation is declared - a row that vanished here would "
              "read as checked: %r" % (_levels(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["OK"]
              and "no derivation is declared" in _detail(rep, "shadow recall"))

        shadow_mode = {"meta": {"phaseGate": {"mode": "shadow"}}, "phases": []}
        rep = base.Report()
        M.check_shadow_recall(rep, recall, manifest_rel, shadow_mode)
        check("dsr2 mode shadow declared and no shadow row recorded yet: an "
              "OK row saying none recorded, never a warning that recall "
              "could not be established: %r"
              % (_detail(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["OK"]
              and "none recorded" in _detail(rep, "shadow recall"))

        # dsr2b ALLOW, and the case the "count a plain row as a shadow run"
        # mutation actually needs: a ledger that carries rows, but none of
        # them a `shadow` field, must still read "none recorded" - not a
        # computed recall with `n/a` percentages. dsr4 below adds a plain
        # row ALONGSIDE two shadow rows, where a plain row's (0, 0)
        # contributes nothing to either sum and so cannot tell this
        # mutation from the fix; this case is a ledger with ONLY a plain
        # row, where the mutation flips the branch itself (OK -> WARNING).
        _plain_row(recall, "s0", "2026-01-01T12:00:00Z")
        rep = base.Report()
        M.check_shadow_recall(rep, recall, manifest_rel, shadow_mode)
        check("dsr2b ALLOW: a ledger holding only a row with no `shadow` "
              "field still reads 'none recorded', not a computed recall: "
              "%r" % (_detail(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["OK"]
              and "none recorded" in _detail(rep, "shadow recall"))

        # dsr3 (RED-FIRST, and the mutation pin): two shadow runs whose
        # SUITE-weighted and RUN-weighted recall disagree - one failing
        # suite listed of one (a run that "caught" its only failure) beside
        # three failing suites with none listed (a run that caught nothing).
        # The suite-weighted TEST recall the assertion below pins is lower
        # than a version that counted RUNS instead of SUITES (the mutation
        # this case pins) would read it as, because that version reads it
        # as CHANGE recall's own number instead - so the two must print
        # DIFFERENT percentages below or the mutation has gone unnoticed.
        _shadow_row(recall, "s1", "2026-01-01T00:00:00Z", 1, 1, missed=[])
        _shadow_row(recall, "s2", "2026-01-02T00:00:00Z", 0, 3,
                   missed=["tests/test_a.py", "tests/test_b.py",
                          "tests/test_c.py"])
        rep = base.Report()
        M.check_shadow_recall(rep, recall, manifest_rel, shadow_mode)
        check("dsr3 test recall is SUITE-weighted (1/4 = 25%%), not "
              "RUN-weighted (which would read 50%%, change recall's own "
              "number) - the mutation this case exists to catch: %r"
              % (_detail(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["WARNING"]
              and "25%" in _detail(rep, "shadow recall")
              and "1/4" in _detail(rep, "shadow recall"))
        check("dsr3b change recall is RUN-weighted (1/2 = 50%%): one of the "
              "two shadow runs had at least one failing suite listed: %r"
              % (_detail(rep, "shadow recall"),),
              "50%" in _detail(rep, "shadow recall")
              and "1/2" in _detail(rep, "shadow recall"))
        check("dsr3c the remedy is the fixed 'switch to enforce' sentence, "
              "with no threshold deciding anything for the reader: %r"
              % (_fix(rep, "shadow recall"),),
              "meta.phaseGate.mode" in _fix(rep, "shadow recall")
              and "enforce" in _fix(rep, "shadow recall"))

        # dsr4 ALLOW CASE: a run that computed no derived gate at all must
        # contribute nothing to either recall - not a phantom failing suite,
        # not a phantom run.
        _plain_row(recall, "s3", "2026-01-03T00:00:00Z")
        rep = base.Report()
        M.check_shadow_recall(rep, recall, manifest_rel, shadow_mode)
        check("dsr4 ALLOW: a row with no `shadow` field leaves both counts "
              "exactly where they were - 1/4 and 1/2, never 1/3 runs: %r"
              % (_detail(rep, "shadow recall"),),
              "25%" in _detail(rep, "shadow recall")
              and "1/4" in _detail(rep, "shadow recall")
              and "1/2" in _detail(rep, "shadow recall"))
    finally:
        shutil.rmtree(recall, ignore_errors=True)

    # --- check_shadow_recall: an unreadable ledger is SAID, never folded --
    # --- into "no shadow runs recorded" ---------------------------------------
    unread = _harness.fixture_root("doctor-trail-shadow-recall-unreadable-")
    try:
        os.makedirs(os.path.join(unread, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        _shadow_row(unread, "u1", "2026-01-01T00:00:00Z", 1, 1, missed=[])
        files = _evidence_io.ledger_files(unread)
        with open(files[0], "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        rep = base.Report()
        M.check_shadow_recall(rep, unread, manifest_rel,
                              {"meta": {"phaseGate": {"mode": "shadow"}}})
        check("dsr5 RED-FIRST: an unparseable ledger line is a WARNING that "
              "the evidence ledger was only partly readable, never folded into "
              "'no shadow runs recorded' - no recall figure is printed "
              "over a ledger this check could not fully read: %r"
              % (_detail(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["WARNING"]
              and "the evidence ledger was only partly readable"
                  in _detail(rep, "shadow recall")
              and "none recorded" not in _detail(rep, "shadow recall")
              and "%" not in _detail(rep, "shadow recall"))
    finally:
        shutil.rmtree(unread, ignore_errors=True)

    # --- check_shadow_recall: CHANGE recall's denominator is RED shadow ---
    # --- runs, never every row that merely carries a `shadow` key ------------
    denom = _harness.fixture_root("doctor-trail-shadow-recall-denominator-")
    try:
        os.makedirs(os.path.join(denom, "docs", "audit"))
        manifest_rel = "docs/audit/audit-plan.json"
        # dsr6 (RED-FIRST, denominator): a GREEN wide shadow row (full == 0,
        # nothing failed - `run-test-gate.shadow_gate_claim` records no
        # such row today, but this reads the ledger's OWN shape rather than
        # trusting the one writer that currently exists) beside a RED one
        # that caught its only failing suite. Counting the green row into
        # the denominator would dilute a clean full catch into a half one.
        _shadow_row(denom, "d1", "2026-01-01T00:00:00Z", 0, 0, missed=[])
        _shadow_row(denom, "d2", "2026-01-02T00:00:00Z", 1, 1, missed=[])
        shadow_mode2 = {"meta": {"phaseGate": {"mode": "shadow"}}, "phases": []}
        rep = base.Report()
        M.check_shadow_recall(rep, denom, manifest_rel, shadow_mode2)
        check("dsr6 CHANGE recall's denominator is RED shadow runs only - "
              "one red run, fully caught, reads 100%% and never the 50%% "
              "counting the green row into the denominator would give: %r"
              % (_detail(rep, "shadow recall"),),
              _levels(rep, "shadow recall") == ["WARNING"]
              and "100%" in _detail(rep, "shadow recall")
              and "1/1 red shadow run" in _detail(rep, "shadow recall"))
    finally:
        shutil.rmtree(denom, ignore_errors=True)

    # --- check_full_run: its own fresh project --------------------------------
    def _full_row(project, run_id, ts, head, commands, ran_total=3,
                 dirty_outside=(), status="passed"):
        """One well-formed scope-`full` row - `full_status`'s own tests build
        one the same way (`_fs_row` in `test__evidence_io.py`): every command
        carried verbatim, every step timed, a positive count with a basis and
        a clean `dirtyOutside`."""
        row = {"v": _evidence_io.ROW_VERSION, "runId": run_id, "ts": ts,
              "scope": _evidence_io.FULL_SCOPE, "status": status,
              "steps": [{"name": "gate", "command": c, "exit": 0,
                        "durationMs": 1000} for c in commands],
              "testedState": {"head": head},
              "observations": {"ranTotal": ran_total, "countsBasis": "3 checks",
                               "dirtyOutside": list(dirty_outside)}}
        _evidence_io.append_row(project, row)
        return row

    full1 = _harness.fixture_root("doctor-trail-full-run-")
    try:
        os.makedirs(os.path.join(full1, "docs", "audit"))
        mrel = "docs/audit/audit-plan.json"

        # dfr1: no meta.fullGate at all is an OK row naming the plan's own
        # words for it - a plan naming no third place has nothing to ask,
        # and nothing else here is even read.
        rep = base.Report()
        M.check_full_run(rep, full1, mrel, {"meta": {}, "phases": []}, full1)
        check("dfr1 no meta.fullGate is an OK row saying no third place is "
              "declared: %r" % (_detail(rep, "full run"),),
              _levels(rep, "full run") == ["OK"]
              and "no third place declared (meta.fullGate)"
                  in _detail(rep, "full run"))

        declared = {"meta": {"fullGate": ["echo x"]}, "phases": []}

        # dfr2 ALLOW: fullGate declared, no phase has merged yet.
        rep = base.Report()
        M.check_full_run(rep, full1, mrel, declared, full1)
        check("dfr2 ALLOW: fullGate declared but no phase has merged yet is "
              "a clean OK, not a warning about phases that do not exist: %r"
              % (_detail(rep, "full run"),),
              _levels(rep, "full run") == ["OK"]
              and "no phase has merged yet" in _detail(rep, "full run"))

        # dfr3 (RED-FIRST, and the repro this task's own tests.add names): one
        # PROVISIONAL phase (a mergedHead recorded, no full-scope run ever
        # recorded) beside one UNKNOWN phase (no mergedHead at all) draws
        # BOTH warnings, each with its own phase id - and the provisional one
        # carries the settle command.
        two_phase = {"meta": {"fullGate": ["echo x"]},
                    "phases": [{"id": "P1", "status": "done",
                               "mergedAt": "2026-01-01T00:00:00Z",
                               "mergedHead": "a" * 40},
                              {"id": "P2", "status": "done",
                               "mergedAt": "2026-01-01T00:00:00Z"}]}
        rep = base.Report()
        M.check_full_run(rep, full1, mrel, two_phase, full1)
        check("dfr3 RED-FIRST: a provisional phase and an unknown phase each "
              "draw their own WARNING: %r" % (rep.rows,),
              _levels(rep, "full run") == ["WARNING", "WARNING"])
        check("dfr3b the provisional row names P1 and carries the settle "
              "command (/audit:review): %r" % (_detail(rep, "full run"),),
              "P1" in _detail(rep, "full run")
              and "PROVISIONAL" in _detail(rep, "full run")
              and "/audit:review P1 --full" in _fix(rep, "full run"))
        check("dfr3c the unknown row names P2 and full_status's own basis "
              "(no mergedHead recorded): %r" % (_detail(rep, "full run"),),
              "P2" in _detail(rep, "full run")
              and "UNKNOWN" in _detail(rep, "full run")
              and "no mergedHead" in _detail(rep, "full run"))

        # dfr4: a full row disqualified for a rule OTHER than "never
        # recorded" - a dirty tree - is named with the rule it failed
        # (`full_status`'s own basis, never re-derived here).
        _full_row(full1, "run-dirty", "2026-01-01T00:00:00Z", "b" * 40,
                 ["echo x"], dirty_outside=["src/app.ts"])
        dirty_phase = {"meta": {"fullGate": ["echo x"]},
                      "phases": [{"id": "P3", "status": "done",
                                 "mergedAt": "2026-01-01T00:00:00Z",
                                 "mergedHead": "b" * 40}]}
        rep = base.Report()
        M.check_full_run(rep, full1, mrel, dirty_phase, full1)
        check("dfr4 a disqualified full run is named with the rule it "
              "failed (a dirty tree), never re-derived as a fresh sentence: "
              "%r" % (_detail(rep, "full run"),),
              _levels(rep, "full run") == ["WARNING"]
              and "DIRTY TREE" in _detail(rep, "full run"))
    finally:
        shutil.rmtree(full1, ignore_errors=True)

    # --- check_full_run: an unreadable ledger is SAID, never folded into ------
    # --- "no phase has merged yet" or a phase's own PROVISIONAL/UNKNOWN ------
    full_unread = _harness.fixture_root("doctor-trail-full-run-unreadable-")
    try:
        os.makedirs(os.path.join(full_unread, "docs", "audit"))
        mrel = "docs/audit/audit-plan.json"
        _full_row(full_unread, "u1", "2026-01-01T00:00:00Z", "c" * 40,
                 ["echo x"])
        files = _evidence_io.ledger_files(full_unread)
        with open(files[0], "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        rep = base.Report()
        M.check_full_run(rep, full_unread, mrel,
                         {"meta": {"fullGate": ["echo x"]},
                          "phases": [{"id": "P1", "status": "done",
                                     "mergedAt": "2026-01-01T00:00:00Z",
                                     "mergedHead": "c" * 40}]},
                         full_unread)
        check("dfr5 RED-FIRST: an unparseable ledger line is a WARNING that "
              "the evidence ledger was only partly readable, never folded into a "
              "phase verdict - no PROVISIONAL/UNKNOWN row is printed over a "
              "ledger this check could not fully read: %r"
              % (_detail(rep, "full run"),),
              _levels(rep, "full run") == ["WARNING"]
              and "the evidence ledger was only partly readable"
                  in _detail(rep, "full run")
              and "P1" not in _detail(rep, "full run"))
    finally:
        shutil.rmtree(full_unread, ignore_errors=True)

    # --- check_full_run: ALLOW - every merged phase reads WHOLE --------------
    def _real_two_commits(root):
        """A REAL git repository at `root`, two sequential commits on
        `main` - `full_status`'s own ancestry needs REAL, DIFFERENT,
        ancestor-related commits (see `test__evidence_io.py`'s twin of this
        fixture), because a fake head/mergedHead pair could pass on a
        `head == mergedHead` mutation as easily as on real containment."""
        os.makedirs(root, exist_ok=True)
        git = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
              "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

        def sh(*args):
            subprocess.run(git + list(args), cwd=root, check=True,
                          capture_output=True, timeout=30)

        def rev():
            out = subprocess.run(git + ["rev-parse", "HEAD"], cwd=root,
                                 check=True, capture_output=True, timeout=30)
            return out.stdout.decode("utf-8").strip()

        sh("init", "-q")
        with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("1\n")
        sh("add", "-A")
        sh("commit", "-qm", "one")
        first = rev()
        with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("2\n")
        sh("add", "-A")
        sh("commit", "-qm", "two")
        second = rev()
        return {"root": root, "first": first, "second": second}

    full_whole = _harness.fixture_root("doctor-trail-full-run-whole-")
    try:
        os.makedirs(os.path.join(full_whole, "docs", "audit"))
        mrel = "docs/audit/audit-plan.json"
        repo = _real_two_commits(os.path.join(full_whole, "repo"))
        _full_row(full_whole, "run-whole", "2026-01-02T00:00:00Z",
                 repo["second"], ["echo x"])
        whole_phase = {"meta": {"fullGate": ["echo x"]},
                      "phases": [{"id": "P1", "status": "done",
                                 "mergedAt": "2026-01-01T00:00:00Z",
                                 "mergedHead": repo["first"]}]}
        rep = base.Report()
        M.check_full_run(rep, full_whole, mrel, whole_phase, repo["root"])
        check("dfr6 ALLOW: every merged phase reads WHOLE draws ONE OK row "
              "naming the run (id and head), not one row per phase: %r"
              % (_detail(rep, "full run"),),
              _levels(rep, "full run") == ["OK"]
              and "run-whole" in _detail(rep, "full run")
              and repo["second"] in _detail(rep, "full run"))
    finally:
        shutil.rmtree(full_whole, ignore_errors=True)

    # --- check_full_run: the SAME phases every other surface asks about -------
    # The doctor, the status, the report and the panel all read this same
    # fixture. It carries the phases a second reading of "merged" would
    # disagree about: one with mergedAt whose effective status is still in
    # progress (merged, not done), one done without mergedAt (done, not
    # merged), and an id-less phase with mergedAt that no surface can name.
    # The ledger is empty, so every merged phase reads PROVISIONAL without
    # git being asked anything.
    full_same = _harness.fixture_root("doctor-trail-full-run-same-")
    try:
        os.makedirs(os.path.join(full_same, "docs", "audit"))
        mrel = "docs/audit/audit-plan.json"
        same_plan = {
            "meta": {"version": 2, "title": "t", "fullGate": ["echo x"]},
            "phases": [
                {"id": "PA", "title": "a", "status": "in_progress",
                 "mergedAt": "2026-01-01T00:00:00Z", "mergedHead": "a" * 40,
                 "tasks": [{"id": "PA.1", "title": "t", "status": "pending"}]},
                {"id": "PD", "title": "d", "status": "done",
                 "mergedHead": "b" * 40,
                 "tasks": [{"id": "PD.1", "title": "t", "status": "done"}]},
                {"title": "no id", "status": "done",
                 "mergedAt": "2026-01-01T00:00:00Z", "mergedHead": "c" * 40,
                 "tasks": []}],
            "fileIndex": {}}
        same_path = os.path.join(full_same, mrel)
        with open(same_path, "w", encoding="utf-8") as fh:
            json.dump(same_plan, fh)

        rep = base.Report()
        M.check_full_run(rep, full_same, mrel, same_plan, full_same)
        doctor_ids = sorted(set(re.findall(
            r"phase (\S+) is (?:PROVISIONAL|UNKNOWN)", _detail(rep, "full run"))))

        def _asked(select):
            # A surface that raises on this fixture (an id-less phase it
            # tried to key a verdict by) is reported as what it raised, so
            # the case below names the surface rather than aborting the suite.
            try:
                return sorted(str(k) for k in select())
            except Exception as exc:
                return ["raised %s" % (type(exc).__name__,)]

        status_mod = _loader.load_script("audit-status.py",
                                         modname="dt_audit_status")
        status_ids = _asked(lambda: status_mod.full_run_block(
            same_plan, same_path, full_same))
        report_mod = _loader.load_script("render-report.py",
                                         modname="dt_render_report")
        report_ids = _asked(lambda: report_mod._full_run_block(
            same_plan, same_path, full_same))
        panel_cmds = _panel_composition.full_gate_commands(same_plan)
        panel_ids = _asked(lambda: [
            p.get("id") for p in same_plan["phases"]
            if _panel_composition._phase_full_run(
                p, panel_cmds, [], full_same) is not None])
        check("dfr7 RED-FIRST: the doctor, the status, the report and the "
              "panel ask about exactly the same phases - the one carrying "
              "mergedAt though it does not read done, never the done one "
              "without mergedAt, never the one with no id: doctor %r, status "
              "%r, report %r, panel %r"
              % (doctor_ids, status_ids, report_ids, panel_ids),
              doctor_ids == status_ids == report_ids == panel_ids == ["PA"])
    finally:
        shutil.rmtree(full_same, ignore_errors=True)


def _ledger_failure_cases(check):
    """A ledger read that FAILED, and a ledger nobody could LOCATE, each worded
    once - by `_manifest_vocab`'s templates, on every check that reads it.

    Two facts with two repairs, which one `try` around both steps used to fold
    into one sentence. The manifest below reaches the read in all four checks:
    a budget for the economy, a shadow mode for recall, a third place and one
    merged phase for the full run."""
    import _manifest_vocab
    root = _harness.fixture_root("doctor-trail-ledger-failures-")
    manifest = {"meta": {"gateBudgetMs": 60000,
                         "phaseGate": {"mode": "shadow"},
                         "fullGate": ["echo x"]},
                "phases": [{"id": "P1", "status": "done",
                            "mergedAt": "2026-01-01T00:00:00Z",
                            "mergedHead": "d" * 40}]}
    mrel = "docs/audit/audit-plan.json"
    names = ("gate patterns", "gate economy", "shadow recall", "full run")

    def _all_four():
        rep = base.Report()
        M.check_gate_patterns(rep, root, mrel)
        M.check_gate_economy(rep, root, mrel, manifest)
        M.check_shadow_recall(rep, root, mrel, manifest)
        M.check_full_run(rep, root, mrel, manifest, root)
        return dict((n, (_levels(rep, n), _detail(rep, n))) for n in names)

    def _boom(*_a, **_k):
        raise OSError("permission denied (fixture)")
    err = "permission denied (fixture)"
    try:
        os.makedirs(os.path.join(root, "docs", "audit"))
        real_read, real_locate = _evidence_io.read_rows, _evidence_io.project_config_for
        _evidence_io.read_rows = _boom
        try:
            unread = _all_four()
        finally:
            _evidence_io.read_rows = real_read
        _evidence_io.project_config_for = _boom
        try:
            unlocated = _all_four()
        finally:
            _evidence_io.project_config_for = real_locate
        want_read = _manifest_vocab.LEDGER_READ_FAILED % (err,)
        want_locate = _manifest_vocab.LEDGER_LOCATION_FAILED % (err,)
        check("dlf1 a ledger read that RAISES is one WARNING on each of the "
              "four checks, worded by the vocabulary's read template and "
              "nothing else: %r" % (unread,),
              all(unread[n] == (["WARNING"], want_read) for n in names))
        check("dlf2 a ledger nobody could LOCATE is the location template on "
              "each of the four, never the read template - the repair is a "
              "different one: %r" % (unlocated,),
              all(unlocated[n] == (["WARNING"], want_locate) for n in names))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --- check_ttl_trade ------------------------------------------------------------
# A plain pricing table, shaped like `usage_ledger`'s own (model -> rates) - the
# two rates the trade actually reads.
_TTL_PRICING = {"claude-sonnet-5": {"in": 2.0, "out": 10.0, "cacheW5m": 2.5,
                                    "cacheW1h": 4.0, "cacheR": 0.2}}

_TTL_BASE_TS = 1760000000  # arbitrary epoch; only the GAPS between entries matter


def _ttl_iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + ".000Z"


def _ttl_assistant_line(mid, epoch, cache_w1h, model="claude-sonnet-5",
                        stop_reason="end_turn"):
    return json.dumps({
        "type": "assistant",
        "timestamp": _ttl_iso(epoch),
        "message": {
            "id": mid, "model": model, "stop_reason": stop_reason,
            "usage": {
                "input_tokens": 100, "output_tokens": 50,
                "cache_creation_input_tokens": cache_w1h,
                "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                  "ephemeral_1h_input_tokens": cache_w1h},
                "cache_read_input_tokens": 0}}})


def _ttl_write(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _ttl_trade_cases(check):
    ul = _loader.load_script("usage_ledger.py", modname="dt_ttl_ledger")
    tmp = _harness.fixture_root("doctor-trail-ttl-")
    try:
        rep = base.Report()
        M.check_ttl_trade(rep, None)
        check("dt55 no transcript named is a documentation-only OK that names "
              "the flag, never a guess: %r" % (_detail(rep, "ttl trade"),),
              _levels(rep, "ttl trade") == ["OK"]
              and "nothing to measure" in _detail(rep, "ttl trade")
              and "--transcript" in _detail(rep, "ttl trade"))

        rep = base.Report()
        M.check_ttl_trade(rep, os.path.join(tmp, "missing.jsonl"))
        check("dt56 a transcript that cannot be read is a WARNING naming the "
              "path, not a silent zero: %r" % (_detail(rep, "ttl trade"),),
              _levels(rep, "ttl trade") == ["WARNING"]
              and "could not be read" in _detail(rep, "ttl trade"))

        one = os.path.join(tmp, "one.jsonl")
        _ttl_write(one, [_ttl_assistant_line("m1", _TTL_BASE_TS, 1000)])
        rep = base.Report()
        M.check_ttl_trade(rep, one, _TTL_PRICING)
        check("dt57 a single main-loop request has no gap to measure: %r"
              % (_detail(rep, "ttl trade"),),
              _levels(rep, "ttl trade") == ["OK"]
              and "fewer than two" in _detail(rep, "ttl trade"))

        zero = os.path.join(tmp, "zero.jsonl")
        _ttl_write(zero, [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 0),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 60, 0)])
        rep = base.Report()
        M.check_ttl_trade(rep, zero, _TTL_PRICING)
        check("dt58 two requests with no one-hour write at all have no TTL "
              "trade to show, and the gap is still named: %r"
              % (_detail(rep, "ttl trade"),),
              _levels(rep, "ttl trade") == ["OK"]
              and "no one-hour cache writes" in _detail(rep, "ttl trade"))

        under = os.path.join(tmp, "under.jsonl")
        _ttl_write(under, [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 60, 1000),
            _ttl_assistant_line("m3", _TTL_BASE_TS + 180, 1000)])
        rep = base.Report()
        M.check_ttl_trade(rep, under, None)
        check("dt59 no pricing table given is a WARNING naming the token "
              "count it could not price, never a guessed dollar figure: %r"
              % (_detail(rep, "ttl trade"),),
              _levels(rep, "ttl trade") == ["WARNING"]
              and "no pricing table was given" in _detail(rep, "ttl trade"))

        rep = base.Report()
        M.check_ttl_trade(rep, under, _TTL_PRICING)
        detail_under = _detail(rep, "ttl trade")
        check("dt60 every gap under five minutes prints THAT longest gap "
              "(120s) and says a five-minute TTL would have cost nothing "
              "extra here: %r" % (detail_under,),
              _levels(rep, "ttl trade") == ["OK"]
              and "120s" in detail_under
              and "would not have forced an extra cache write" in detail_under
              and "$0.0120" in detail_under and "$0.0075" in detail_under)

        over = os.path.join(tmp, "over.jsonl")
        _ttl_write(over, [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 60, 1000),
            _ttl_assistant_line("m3", _TTL_BASE_TS + 400, 1000)])
        rep = base.Report()
        M.check_ttl_trade(rep, over, _TTL_PRICING)
        detail_over = _detail(rep, "ttl trade")
        check("dt61 a gap over five minutes prints THAT longest gap (340s), "
              "says a five-minute TTL would have missed the cache here, and "
              "prices the five-minute side as a FLOOR that leaves out the "
              "re-writes the gap forces - the same-token price alone reads "
              "cheaper exactly when it would not be: %r" % (detail_over,),
              _levels(rep, "ttl trade") == ["OK"]
              and "340s" in detail_over
              and "would have missed the cache at least once" in detail_over
              and "$0.0120" in detail_over
              and "at least $0.0075" in detail_over
              and "leaves out" in detail_over)

        check("dt62 the twin pair shares its token count and both prices - "
              "only the gap, its implication and the floor's wording differ - "
              "and the under-five-minutes side states no floor, since no "
              "re-write is left out there: %r" % ((detail_under, detail_over),),
              "3000 one-hour" in detail_under and "3000 one-hour" in detail_over
              and "$0.0075" in detail_under and "at least" not in detail_under
              and "leaves out" not in detail_under)

        at300 = os.path.join(tmp, "at300.jsonl")
        _ttl_write(at300, [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 300, 1000)])
        rep = base.Report()
        M.check_ttl_trade(rep, at300, _TTL_PRICING)
        detail_300 = _detail(rep, "ttl trade")
        check("dt64 a gap of EXACTLY five minutes is on the expiring side and is "
              "worded as one that REACHES five minutes - never as one that "
              "exceeds them, which it does not, nor as staying under: %r"
              % (detail_300,),
              "300s" in detail_300 and "reaches five minutes" in detail_300
              and "exceeds" not in detail_300
              and "stayed under" not in detail_300)

        side = os.path.join(tmp, "side.jsonl")
        side_lines = [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 690, 1000)]
        # In time order, so read as main-loop requests the two would cut the
        # longest gap to 300s - the misreading this case exists for.
        for k, at in (("s2", 500), ("s1", 200)):
            entry = json.loads(_ttl_assistant_line(k, _TTL_BASE_TS + at, 5000))
            entry["isSidechain"] = True
            side_lines.insert(1, json.dumps(entry))
        _ttl_write(side, side_lines)
        side_entries = M.main_loop_requests(side, ul)
        rep = base.Report()
        M.check_ttl_trade(rep, side, _TTL_PRICING)
        detail_side = _detail(rep, "ttl trade")
        check("dt65 a sidechain entry (an agent's request, `isSidechain: true`) "
              "is not a main-loop request: it neither cuts the main loop's "
              "690s gap nor adds its writes: %r" % ((side_entries, detail_side),),
              side_entries is not None and len(side_entries) == 2
              and "690s" in detail_side and "2000 one-hour" in detail_side)

        dup = os.path.join(tmp, "dup.jsonl")
        _ttl_write(dup, [
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000),
            _ttl_assistant_line("m1", _TTL_BASE_TS, 1000, stop_reason=None),
            _ttl_assistant_line("m2", _TTL_BASE_TS + 60, 2000)])
        entries = M.main_loop_requests(dup, ul)
        check("dt63 a repeated message id (the streaming-partial/final pair) "
              "is folded to ONE request, not counted twice: %r" % (entries,),
              entries is not None and len(entries) == 2
              and entries[0]["cacheW1h"] == 1000)
    finally:
        _harness.remove_tree(tmp)


def _coupling_cases(check):
    """`check_couplings` - a learned coupling that points at a file git no
    longer tracks is NAMED with the command that drops it, and one that has
    gone the constant's worth of green measured full runs without
    catching anything is named as a CANDIDATE. Neither is ever removed: the
    only writer of `meta.coupling` is `audit-task.py`, and a doctor that
    edited it would be narrowing the gate on its own judgement."""
    fn = getattr(M, "check_couplings", None)
    k = getattr(M, "UNCOUPLE_AFTER_FULL_RUNS", 3)
    mrel = "docs/audit/audit-plan.json"

    def _run(project, manifest, git_root):
        rep = base.Report()
        if fn is not None:
            fn(rep, project, mrel, manifest, git_root)
        return rep

    def _rows(rep):
        return [r for r in rep.rows if r["check"] == "coupling"]

    def _git(root, *args):
        subprocess.run(["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
                        "-c", "commit.gpgsign=false",
                        "-c", "init.defaultBranch=main"] + list(args),
                       cwd=root, check=True, capture_output=True, timeout=30)

    def _entry(test, sources, learned, caught=None):
        entry = {"test": test, "sources": list(sources),
                 "basis": {"runId": "run-learn"}, "learnedAt": learned}
        if caught is not None:
            entry["lastCaught"] = caught
        return entry

    # dcp1 ALLOW: no meta.coupling is ONE OK row saying so, never silence.
    rep = _run("/nonexistent-project", {"meta": {}, "phases": []}, None)
    check("dcp1 no meta.coupling is one OK row saying nothing is learned: %r"
          % (_rows(rep),),
          [r["level"] for r in _rows(rep)] == ["OK"]
          and "no meta.coupling" in _rows(rep)[0]["detail"])

    if not shutil.which("git"):
        print("SKIP dcp2-dcp4 (git is not on PATH)")
    else:
        root = _harness.fixture_root("doctor-trail-coupling-tracked-")
        try:
            os.makedirs(os.path.join(root, "docs", "audit"))
            os.makedirs(os.path.join(root, "tests"))
            os.makedirs(os.path.join(root, "src"))
            for rel in ("tests/test_widget.py", "tests/test_gadget.py",
                        "tests/test_other.py",
                        "src/widget.py", "src/gadget.py"):
                with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")
            _git(root, "init", "-q")
            _git(root, "add", "tests", "src")
            _git(root, "commit", "-qm", "one")
            plan = {"meta": {"coupling": [
                _entry("tests/test_widget.py", ["src/widget.py"],
                       "2026-01-01T00:00:00Z"),
                _entry("tests/test_gadget.py", ["src/gadget.py"],
                       "2026-01-01T00:00:00Z")]}, "phases": []}

            # dcp2 ALLOW (the always-fires direction): every named path is
            # tracked, so no row names `uncouple` at all.
            rep = _run(root, plan, root)
            check("dcp2 ALLOW: every coupled path tracked draws no uncouple "
                  "command and no untracked warning: %r" % (_rows(rep),),
                  bool(_rows(rep))
                  and not any("uncouple" in (r.get("fix") or "")
                              for r in _rows(rep))
                  and not any("does not track" in r["detail"]
                              for r in _rows(rep)))

            # The plan ON DISK too, aged into the past, so a doctor that
            # rewrote it - even with identical bytes in the same second - is
            # caught by the mtime as well as by the content.
            plan_path = os.path.join(root, mrel)
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh, indent=2)
            os.utime(plan_path, (1000000000, 1000000000))
            with open(plan_path, "rb") as fh:
                plan_bytes = fh.read()
            plan_mtime = os.stat(plan_path).st_mtime_ns

            # dcp3 RED-FIRST (the repro this task's tests.add names): the
            # coupled test file is deleted and the deletion committed, so git
            # no longer tracks it. The doctor names the path AND the exact
            # command, and names only that entry - the untouched coupling
            # beside it draws nothing.
            _git(root, "rm", "-q", "tests/test_widget.py")
            _git(root, "commit", "-qm", "two")
            rep = _run(root, plan, root)
            warned = [r for r in _rows(rep) if r["level"] == "WARNING"
                      and "does not track" in r["detail"]]
            check("dcp3 RED-FIRST: a coupling whose test git no longer tracks "
                  "is a WARNING naming the path and "
                  "`audit-task.py uncouple --test <path>`: %r" % (_rows(rep),),
                  len(warned) == 1
                  and "tests/test_widget.py" in warned[0]["detail"]
                  and "audit-task.py uncouple --test tests/test_widget.py"
                      in (warned[0].get("fix") or ""))
            check("dcp3b ...and names ONLY that entry - the tracked coupling "
                  "beside it is never offered for uncoupling: %r"
                  % (_rows(rep),),
                  not any("test_gadget" in (r.get("fix") or "")
                          for r in _rows(rep)))
            with open(plan_path, "rb") as fh:
                after_bytes = fh.read()
            check("dcp3c ...and the plan is never edited, neither the dict it "
                  "was handed nor the file on disk (bytes and mtime) - a "
                  "doctor that dropped the entry would narrow the gate: %r"
                  % (plan["meta"]["coupling"],),
                  [e["test"] for e in plan["meta"]["coupling"]]
                  == ["tests/test_widget.py", "tests/test_gadget.py"]
                  and after_bytes == plan_bytes
                  and os.stat(plan_path).st_mtime_ns == plan_mtime)

            # dcp4: an untracked SOURCE is named too, and the command drops
            # the entry by its test - the only key `uncouple` takes.
            src_plan = {"meta": {"coupling": [
                _entry("tests/test_gadget.py",
                       ["src/gadget.py", "src/never_committed.py"],
                       "2026-01-01T00:00:00Z")]}, "phases": []}
            rep = _run(root, src_plan, root)
            warned = [r for r in _rows(rep) if "does not track" in r["detail"]]
            check("dcp4 an untracked source is named, and the command keys "
                  "the entry by its test: %r" % (_rows(rep),),
                  len(warned) == 1
                  and "src/never_committed.py" in warned[0]["detail"]
                  and "src/gadget.py" not in warned[0]["detail"]
                  and "audit-task.py uncouple --test tests/test_gadget.py"
                      in (warned[0].get("fix") or ""))

            # dcp10: a source OUTSIDE the repository (a parent-relative path
            # the coupling verb accepts) is named on its own entry - and git
            # is still asked about every other path, rather than refusing the
            # whole batch and switching the tracking check off for all.
            out_plan = {"meta": {"coupling": [
                _entry("tests/test_gadget.py", ["src/gadget.py"],
                       "2026-01-01T00:00:00Z"),
                _entry("tests/test_other.py", ["src/gadget.py", "../outside.py"],
                       "2026-01-01T00:00:00Z"),
                _entry("tests/test_widget.py", ["src/widget.py"],
                       "2026-01-01T00:00:00Z")]}, "phases": []}
            rep = _run(root, out_plan, root)
            outside = [r for r in _rows(rep) if "outside" in r["detail"]]
            gone = [r for r in _rows(rep) if "does not track" in r["detail"]]
            check("dcp10 an out-of-repository source is named with the "
                  "uncouple command for its entry, and the batch still "
                  "answers for the rest (the deleted test is still named, "
                  "nothing reads 'not checked'): %r" % (_rows(rep),),
                  len(outside) == 1 and "../outside.py" in outside[0]["detail"]
                  and "audit-task.py uncouple --test tests/test_other.py"
                      in (outside[0].get("fix") or "")
                  and len(gone) == 1
                  and "tests/test_widget.py" in gone[0]["detail"]
                  and not any("not checked" in r["detail"]
                              for r in _rows(rep))
                  and not any("test_gadget" in (r.get("fix") or "")
                              for r in _rows(rep)))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # dcp5: not a git repository is a STATED basis, never a crash and never
    # read as "every path tracked".
    rep = _run("/nonexistent-project", {"meta": {"coupling": [
        _entry("tests/test_widget.py", ["src/widget.py"],
               "2026-01-01T00:00:00Z")]}, "phases": []}, None)
    check("dcp5 no git root is a WARNING saying tracking was not checked, "
          "never an OK claiming it was: %r" % (_rows(rep),),
          any(r["level"] == "WARNING" and "not checked" in r["detail"]
              for r in _rows(rep))
          and not any("tracked by git" in r["detail"] for r in _rows(rep)))

    # dcp5b: a git root handed in that git itself refuses (not a repository)
    # is the same stated basis, in git's own words - never "nothing tracked",
    # which would name every coupling as gone at once.
    if shutil.which("git"):
        bare = _harness.fixture_root("doctor-trail-coupling-norepo-")
        try:
            # A `.git` FILE that is not a gitfile makes git refuse here
            # whatever repository the scratch directory happens to sit in.
            with open(os.path.join(bare, ".git"), "w", encoding="utf-8") as fh:
                fh.write("not a gitdir pointer\n")
            rep = _run(bare, {"meta": {"coupling": [
                _entry("tests/test_widget.py", ["src/widget.py"],
                       "2026-01-01T00:00:00Z")]}, "phases": []}, bare)
            check("dcp5b git refusing the directory is a WARNING that "
                  "tracking was not checked, never an untracked-path "
                  "warning: %r" % (_rows(rep),),
                  any(r["level"] == "WARNING" and "not checked" in r["detail"]
                      and "git ls-files exited" in r["detail"]
                      for r in _rows(rep))
                  and not any("does not track" in r["detail"]
                              for r in _rows(rep)))
        finally:
            shutil.rmtree(bare, ignore_errors=True)

    # --- ageing against green measured full runs --------------------------
    def _full(project, run_id, day, status="passed"):
        _evidence_io.append_row(project, {
            "v": _evidence_io.ROW_VERSION, "runId": run_id,
            "ts": "2026-03-%02dT00:00:00Z" % (day,),
            "scope": _evidence_io.FULL_SCOPE, "status": status,
            "steps": [{"name": "gate", "command": "echo x", "exit": 0,
                       "durationMs": 1000}],
            "testedState": {"head": "e" * 40},
            "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                             "dirtyOutside": []}})

    age = _harness.fixture_root("doctor-trail-coupling-age-")
    try:
        os.makedirs(os.path.join(age, "docs", "audit"))
        # K green measured runs on consecutive days from the 2nd, plus
        # one RED full run AFTER all of them - so a reader that aged by every
        # full row rather than by measured ones counts one run more.
        for i in range(k):
            _full(age, "green-%d" % (i,), i + 2)
        _full(age, "red-0", k + 2, status="failed")

        def _aged(entry):
            return {"meta": {"fullGate": ["echo x"], "coupling": [entry]},
                    "phases": []}

        def _candidates(rep):
            return [r for r in _rows(rep) if "CANDIDATE" in r["detail"]]

        # dcp6 ALLOW (the named direction): learned before every run, never
        # caught - K green measured runs since, so it is a candidate,
        # K printed as the basis, and the command named, not run.
        rep = _run(age, _aged(_entry("tests/test_old.py", ["src/old.py"],
                                     "2026-02-01T00:00:00Z")), None)
        cand = _candidates(rep)
        check("dcp6 a coupling older than K green measured full runs is "
              "a CANDIDATE naming K and the uncouple command: %r"
              % (_rows(rep),),
              len(cand) == 1 and "tests/test_old.py" in cand[0]["detail"]
              and "UNCOUPLE_AFTER_FULL_RUNS = %d" % (k,) in cand[0]["detail"]
              and "audit-task.py uncouple --test tests/test_old.py"
                  in (cand[0].get("fix") or ""))

        # dcp7 ALLOW (the never-fires-too-often direction): learned long
        # ago but CAUGHT after the first green run, so fewer than K green
        # runs have passed since - lastCaught outranks learnedAt.
        rep = _run(age, _aged(_entry("tests/test_live.py", ["src/live.py"],
                                     "2026-02-01T00:00:00Z",
                                     caught="2026-03-02T12:00:00Z")), None)
        check("dcp7 ALLOW: a coupling caught recently is NOT a candidate, "
              "however old its learnedAt: %r" % (_rows(rep),),
              not _candidates(rep)
              and any(r["level"] == "OK" for r in _rows(rep)))

        # dcp8: the RED run does not age anything. Learned just after the
        # first green run leaves K-1 green runs plus the red one after them -
        # a candidate only to a reader that counts the red run too.
        rep = _run(age, _aged(_entry("tests/test_mid.py", ["src/mid.py"],
                                     "2026-03-02T12:00:00Z")), None)
        check("dcp8 only GREEN measured runs age a coupling - K-1 of "
              "them is not enough: %r" % (_rows(rep),),
              not _candidates(rep))

        # dcp12: STRICTLY AFTER. learnedAt equal to the first green run's own
        # ts leaves K-1 runs after it; a reader counting that run too (>=
        # where > is meant) reaches K and names a candidate.
        rep = _run(age, _aged(_entry("tests/test_edge.py", ["src/edge.py"],
                                     "2026-03-02T00:00:00Z")), None)
        check("dcp12 a run AT the learnedAt moment does not age the coupling "
              "- only runs strictly after it do: %r" % (_rows(rep),),
              not _candidates(rep)
              and any(r["level"] == "OK" for r in _rows(rep)))

        # dcp9: an entry that cannot be aged names the remedy that actually
        # resets it - `couple` on an already-coupled test only widens it and
        # keeps learnedAt, so the warning would come straight back.
        nolearn = {"test": "tests/test_nolearn.py", "sources": ["src/n.py"],
                   "basis": {"runId": "run-learn"}}
        rep = _run(age, _aged(nolearn), None)
        cannot = [r for r in _rows(rep) if "cannot be aged" in r["detail"]]
        fix = (cannot[0].get("fix") or "") if cannot else ""
        check("dcp9 an entry with no learnedAt names uncouple THEN couple, "
              "never couple alone: %r" % (_rows(rep),),
              len(cannot) == 1
              and "neither lastCaught nor learnedAt" in cannot[0]["detail"]
              and "audit-task.py uncouple --test tests/test_nolearn.py, then "
                  "audit-task.py couple --test tests/test_nolearn.py "
                  "--sources src/n.py --basis-run" in fix
              and "or audit-task.py couple to learn it again" not in fix)

        # dcp11: a green measured row whose ts does not parse ages
        # nothing, and that is SAID - never a silently narrower count.
        _evidence_io.append_row(age, {
            "v": _evidence_io.ROW_VERSION, "runId": "green-undated",
            "ts": "not a moment", "scope": _evidence_io.FULL_SCOPE,
            "status": "passed",
            "steps": [{"name": "gate", "command": "echo x", "exit": 0,
                       "durationMs": 1000}],
            "testedState": {"head": "e" * 40},
            "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                             "dirtyOutside": []}})
        rep = _run(age, _aged(_entry("tests/test_live.py", ["src/live.py"],
                                     "2026-02-01T00:00:00Z",
                                     caught="2026-03-02T12:00:00Z")), None)
        check("dcp11 a green measured run whose ts does not parse is "
              "counted and said, and still ages nothing: %r" % (_rows(rep),),
              any("1 green measured full run(s) carry a ts that does not "
                  "parse" in r["detail"] for r in _rows(rep))
              and not _candidates(rep))
    finally:
        shutil.rmtree(age, ignore_errors=True)

    # dcp13: ageing asks whether a run MEASURED the declared gate green on a
    # clean tree - the chance a coupling had to catch - and a missing tested
    # head says nothing about that. K head-less green runs age a coupling
    # exactly as K headed ones do.
    headless = _harness.fixture_root("doctor-trail-coupling-headless-")
    try:
        os.makedirs(os.path.join(headless, "docs", "audit"))
        for i in range(k):
            _evidence_io.append_row(headless, {
                "v": _evidence_io.ROW_VERSION, "runId": "headless-%d" % (i,),
                "ts": "2026-03-%02dT00:00:00Z" % (i + 2,),
                "scope": _evidence_io.FULL_SCOPE, "status": "passed",
                "steps": [{"name": "gate", "command": "echo x", "exit": 0,
                           "durationMs": 1000}],
                "testedState": {},
                "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                                 "dirtyOutside": []}})
        rep = _run(headless, {"meta": {"fullGate": ["echo x"], "coupling": [
            _entry("tests/test_old.py", ["src/old.py"],
                   "2026-02-01T00:00:00Z")]}, "phases": []}, None)
        cand = [r for r in _rows(rep) if "CANDIDATE" in r["detail"]]
        check("dcp13 RED-FIRST: K green full runs that record no tested head "
              "still age a coupling into a CANDIDATE - a missing head is not "
              "a missed chance to catch: %r" % (_rows(rep),),
              len(cand) == 1 and "tests/test_old.py" in cand[0]["detail"])
    finally:
        shutil.rmtree(headless, ignore_errors=True)

    _muted_coupling_cases(check, _run, _rows, _entry, k)
    _date_only_coupling_cases(check, _entry)
    _relearn_command_cases(check, _run, _rows)


def _muted_full_row(run_id, day, step_mute, row_mute):
    """A green measured full row whose step FAILED with its failure excused
    by a mute - named on the step, on the row, or both."""
    step = {"name": "gate", "command": "echo x", "exit": 1, "durationMs": 1000}
    if step_mute:
        step["muted"] = [{"test": step_mute, "bugId": "BUG-1",
                          "until": "2099-01-01"}]
    row = {"v": _evidence_io.ROW_VERSION, "runId": run_id,
           "ts": "2026-03-%02dT00:00:00Z" % (day,),
           "scope": _evidence_io.FULL_SCOPE, "status": "passed",
           "steps": [step], "testedState": {"head": "e" * 40},
           "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                            "dirtyOutside": []}}
    if row_mute:
        row["muted"] = [{"test": row_mute, "bugId": "BUG-1",
                         "until": "2099-01-01"}]
    return row


def _muted_coupling_cases(check, _run, _rows, _entry, k):
    """A run whose coupled test failed and was MUTED reads green, but the
    test did not pass in it - so it must not age that coupling. The mute is
    spelled `./tests/...` while the coupling says `tests/...`, so a reader
    comparing raw strings goes red too."""
    muted = _harness.fixture_root("doctor-trail-coupling-muted-")
    try:
        os.makedirs(os.path.join(muted, "docs", "audit"))
        # K runs from the 2nd: the first half name the mute on the step
        # only, the rest on the row only, so dropping either reading ages
        # the muted coupling by a count this case can see.
        for i in range(k):
            on_step = i < k // 2
            _evidence_io.append_row(muted, _muted_full_row(
                "muted-%d" % (i,), i + 2,
                "./tests/test_c.py" if on_step else None,
                None if on_step else "./tests/test_c.py"))
        plan = {"meta": {"fullGate": ["echo x"], "coupling": [
            _entry("tests/test_c.py", ["src/c.py"], "2026-02-01T00:00:00Z"),
            _entry("tests/test_d.py", ["src/d.py"], "2026-02-01T00:00:00Z")]},
            "phases": []}
        rep = _run(muted, plan, None)
        cand = [r for r in _rows(rep) if "CANDIDATE" in r["detail"]]
        check("dcp14 RED-FIRST: K green runs in which the coupled test "
              "failed MUTED do not make it a CANDIDATE - it failed every "
              "run, which is not catching nothing: %r" % (_rows(rep),),
              not any("tests/test_c.py" in r["detail"] for r in cand))
        # ALLOW DIRECTION: the same runs age a coupling they did NOT mute,
        # so a version that skipped every row carrying any mute goes red.
        check("dcp15 ALLOW: the same unmuted-for-it green runs still age "
              "the other coupling into a CANDIDATE: %r" % (_rows(rep),),
              len(cand) == 1 and "tests/test_d.py" in cand[0]["detail"])
        rows = _evidence_io.read_rows(muted)["rows"]
        moments, _undated = M._measured_run_moments(rows, ["echo x"])
        ages = [M.coupling_age(_entry(t, ["src/x.py"],
                                      "2026-02-01T00:00:00Z"), moments)[0]
                for t in ("tests/test_c.py", "tests/test_d.py")]
        check("dcp16 RED-FIRST: counted run by run, the muted coupling is "
              "aged by none of the K runs - neither those muting it on the "
              "step nor those muting it on the row - and the other by all "
              "K: %r (K=%d)" % (ages, k),
              ages == [0, k])
    finally:
        shutil.rmtree(muted, ignore_errors=True)


def _date_only_coupling_cases(check, _entry):
    """A date-only stamp is a moment to the ledger's own ordering
    (`_evidence_io.stamp_moment`, the start of that day in UTC), so ageing
    must read it as the same moment rather than as no moment at all."""
    row = {"v": _evidence_io.ROW_VERSION, "runId": "dated", "ts": "2026-03-05",
           "scope": _evidence_io.FULL_SCOPE, "status": "passed",
           "steps": [{"name": "gate", "command": "echo x", "exit": 0,
                      "durationMs": 1000}],
           "testedState": {"head": "e" * 40},
           "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                            "dirtyOutside": []}}
    moments, undated = M._measured_run_moments([row], ["echo x"])
    want = _evidence_io.stamp_moment("2026-03-05")
    check("dcp17 RED-FIRST: a green measured run stamped with a date alone "
          "is placed at the moment the ledger orders it by, not counted as "
          "undated: %r (want %r)" % ((moments, undated), want),
          undated == 0 and [m for m, _muted in moments] == [want]
          and want is not None)
    before = M.coupling_age(_entry("tests/test_e.py", ["src/e.py"],
                                   "2026-03-04"), moments)
    same = M.coupling_age(_entry("tests/test_e.py", ["src/e.py"],
                                 "2026-03-05"), moments)
    check("dcp18 RED-FIRST: a date-only learnedAt is a moment too - the day "
          "before the run is aged by it, the run's own day (the same "
          "moment) is not: %r" % ((before, same),),
          before[0] == 1 and same[0] == 0 and before[2] is None
          and same[2] is None)


def _relearn_command_cases(check, _run, _rows):
    """The remedy printed for an entry that cannot be aged is a command a
    reader types: `couple` refuses to learn without every basis flag, so
    the printed one is RUN - its placeholders filled from a fixture - and
    must be accepted."""
    fixture = _harness.fixture_root("doctor-trail-coupling-relearn-")
    try:
        os.makedirs(os.path.join(fixture, ".claude"))
        os.makedirs(os.path.join(fixture, "docs", "audit"))
        with open(os.path.join(fixture, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        plan = {"meta": {"version": 2, "buildCommands": {"test": "true"},
                         "fullGate": ["echo x"]},
                "phases": [{"id": "P1", "title": "Live",
                            "status": "in_progress", "testGate": ["test"],
                            "tasks": [{"id": "P1.1", "title": "a",
                                       "status": "pending"}]}],
                "fileIndex": {}, "bugs": []}
        with open(os.path.join(fixture, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2)
        _evidence_io.append_row(fixture, {
            "v": _evidence_io.ROW_VERSION, "runId": "run-relearn",
            "ts": "2026-03-02T00:00:00Z", "scope": _evidence_io.FULL_SCOPE,
            "status": "failed",
            "steps": [{"name": "gate", "command": "echo x", "exit": 1,
                       "durationMs": 1000}],
            "testedState": {"head": "e" * 40},
            "observations": {"ranTotal": 3, "countsBasis": "3 checks",
                             "dirtyOutside": []}})
        unaged = {"test": "tests/test_re.py", "sources": ["src/re.py"],
                  "basis": {"runId": "run-learn"}}
        rep = _run(fixture, {"meta": {"fullGate": ["echo x"],
                                      "coupling": [unaged]},
                             "phases": []}, None)
        cannot = [r for r in _rows(rep) if "cannot be aged" in r["detail"]]
        fix = (cannot[0].get("fix") or "") if cannot else ""
        marker = "then audit-task.py couple "
        tail = fix.split(marker, 1)[1] if marker in fix else ""
        printed = "couple " + tail.split(" to learn it again", 1)[0]
        values = {"--basis-run": "run-relearn", "--basis-head": "e" * 40,
                  "--phases": "P1"}
        missing = []

        def fill(match):
            flag = match.group(1)
            if flag not in values:
                missing.append(flag)
                return match.group(0)
            return "%s %s" % (flag, values[flag])
        argv = shlex.split(re.sub(r"(--[\w-]+) <[^>]*>", fill, printed))
        task = _loader.load_script("audit-task.py", modname="audit_task_dcp")
        said = []
        code = task.main(argv + ["--project-dir", fixture], out=said.append)
        coupled = []
        with open(os.path.join(fixture, "docs", "audit", "audit-plan.json"),
                  encoding="utf-8") as fh:
            coupled = (json.load(fh).get("meta") or {}).get("coupling") or []
        check("dcp19 RED-FIRST: the couple command the doctor prints for an "
              "entry that cannot be aged, its placeholders filled, is "
              "ACCEPTED by audit-task.py couple and learns the entry - every "
              "flag couple requires is spelled: %r -> %r %r (%r)"
              % (argv, code, said, coupled),
              bool(tail) and not missing and code == 0
              and [e.get("test") for e in coupled] == ["tests/test_re.py"]
              and (coupled[0].get("basis") or {}).get("phases") == ["P1"])
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


def _selftest():
    def body(check):
        _cases(check)
        _ledger_failure_cases(check)
        _ttl_trade_cases(check)
        _coupling_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_trail.py --selftest\n")
    raise SystemExit(2)
