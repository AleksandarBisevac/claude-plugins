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

        # ------------------------------- which WARNING class, and its fix (F329)
        # THE PAIR IS THE POINT. F306 made a re-linked file a warning instead of
        # a finding, and the fix text stayed the single sentence about
        # out-of-band drift - so the highest-stakes new class told an operator
        # to look for a git checkout that does not exist. dt43 fails when the
        # classifier never fires (the original defect); dt44 fails when it fires
        # unconditionally, which is the other wrong implementation and the one
        # that looks vacuous. Both fixtures are REAL: a spliced-and-re-chained
        # committed file, and a recorded document edited behind the journal's
        # back.
        #
        # AND THE SAME PAIR AGAIN ONE LEVEL DOWN (F344a). `_anchor_warning` says
        # two different things and both open with the same clause, so `relink`
        # keyed on that clause answered for a file where NO row moved and none
        # arrived - F329's own defect, reintroduced by the repair. dt46 is the
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
                  "and read rows that do not exist. This is F329's defect one "
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
        # red when its sentence is reworded and this one had no case at all
        # (F344c): rewording `verify`'s partial-line warning left the whole
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

        # F344b, and the fixture is real rather than two hand-written strings:
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

        # ------------------------------------------- check_running_plugin (F228)
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
        v = M.running_plugin_verdict(
            here, [dict(elsewhere, session="old", mtime=1)], [], [])
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
            here, [dict(elsewhere, session="old", mtime=1)], [],
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
